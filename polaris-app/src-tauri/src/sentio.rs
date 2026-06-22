//! 板块 · SENTIO 选股达人「立即检查」
//!
//! 前端点「立即检查」→ 本命令 spawn data-pipeline 的 run_all.py（采集情绪 + 多因子策略 + 回测），
//! 逐行 stdout 作进度事件 `sentio:progress` 上报，结束 emit `sentio:done` / `sentio:error`。
//! 产物 board.json / sentiment_latest.json / strategy.json 落到 <前端目录>/sentio/，
//! 前端三屏 + 建议策略页通过 `sentio_read` 命令（打包态读 app-data，开发态读仓库 public/）拿到最新结果。
//!
//! 仅桌面端。Python 运行时与 data-pipeline 源码随安装包内置（resources/pyruntime + resources/data-pipeline），
//! 用户机器无需自装 Python/akshare；打包态把脚本复制到 app-data 可写副本里跑，开发态直接跑仓库源码。

use serde::Serialize;
use std::fs;
use std::io::{BufRead, BufReader};
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::sync::atomic::{AtomicBool, Ordering};
use tauri::{AppHandle, Emitter, Manager};
use walkdir::WalkDir;

#[cfg(windows)]
const CREATE_NO_WINDOW: u32 = 0x0800_0000;

#[cfg_attr(not(windows), allow(unused_variables))]
fn no_window(cmd: &mut Command) {
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        cmd.creation_flags(CREATE_NO_WINDOW);
    }
}

/// 单飞：同一时刻只允许一次采集分析在跑，避免东财/新浪被并发请求触发限流。
static RUNNING: AtomicBool = AtomicBool::new(false);

#[derive(Clone, Serialize)]
struct ProgressEvent {
    line: String,
    /// 0..=100 粗略进度（按已处理标的数估算），-1 表示未知阶段。
    pct: i32,
}

#[derive(Clone, Serialize)]
struct DoneEvent {
    ok: bool,
    code: i32,
    message: String,
}

// ───────────────────────── 内置 Python 运行时 ─────────────────────────

/// 内置 Python 解释器路径：优先安装包里的 resources/pyruntime，开发期回退 src-tauri/resources/pyruntime，
/// 都没有再回退系统 PATH 的 python/python3/py（开发机自装环境）。返回可执行文件绝对路径或命令名。
fn resolve_python(app: &AppHandle) -> Option<PathBuf> {
    // pyruntime 内 python 可执行文件的相对位置（Win 在根、*nix 在 bin/）。
    #[cfg(windows)]
    let rel: &[&str] = &["python.exe"];
    #[cfg(not(windows))]
    let rel: &[&str] = &["bin/python3", "bin/python"];

    let mut roots: Vec<PathBuf> = Vec::new();
    if let Ok(rd) = app.path().resource_dir() {
        roots.push(rd.join("resources").join("pyruntime"));
        roots.push(rd.join("pyruntime"));
    }
    // 开发期：本地 prepare 脚本把 pyruntime 放到 src-tauri/resources/pyruntime，便于不打包也能验证内置 python。
    roots.push(PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("resources").join("pyruntime"));

    for root in roots {
        for r in rel {
            let p = root.join(r);
            if p.exists() {
                return Some(p);
            }
        }
    }

    // 回退：系统已装的 python（仅开发机/未内置时）。
    for cand in ["python", "python3", "py"] {
        let mut c = Command::new(cand);
        c.arg("--version");
        no_window(&mut c);
        if let Ok(out) = c.output() {
            if out.status.success() {
                return Some(PathBuf::from(cand));
            }
        }
    }
    None
}

/// 是否为「内置发布态」：安装包里带了 data-pipeline 资源。是→脚本要复制到可写目录跑；否→开发态原地跑仓库源码。
fn bundled_pipeline_source(app: &AppHandle) -> Option<PathBuf> {
    if let Ok(rd) = app.path().resource_dir() {
        for cand in [rd.join("resources").join("data-pipeline"), rd.join("data-pipeline")] {
            if cand.join("run_all.py").exists() {
                return Some(cand);
            }
        }
    }
    None
}

/// 开发态仓库内 data-pipeline（源码原地跑，产物直接进仓库 public/，Vite 实时可见）。
fn dev_pipeline_dir() -> Option<PathBuf> {
    // CARGO_MANIFEST_DIR = .../polaris-app/src-tauri → 仓库根 = 上两级
    let manifest = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    if let Some(repo) = manifest.parent().and_then(|p| p.parent()) {
        let d = repo.join("data-pipeline");
        if d.join("run_all.py").exists() {
            return Some(d);
        }
    }
    if let Ok(cwd) = std::env::current_dir() {
        for c in [cwd.join("data-pipeline"), cwd.parent().map(|p| p.join("data-pipeline")).unwrap_or_default()] {
            if c.join("run_all.py").exists() {
                return Some(c);
            }
        }
    }
    None
}

/// 脚本运行（可写）目录：
/// - `SENTIO_PIPELINE_DIR` 显式覆盖优先；
/// - 内置发布态：app-data/pipeline（资源是只读的，必须复制到可写副本）；
/// - 开发态：仓库 data-pipeline 原地。
/// 仅返回路径，不触发复制（复制由 `ensure_pipeline` 负责，避免读 JSON 时也复制）。
fn pipeline_work_dir(app: &AppHandle) -> Option<PathBuf> {
    if let Ok(p) = std::env::var("SENTIO_PIPELINE_DIR") {
        let pb = PathBuf::from(p);
        if pb.join("run_all.py").exists() {
            return Some(pb);
        }
    }
    if bundled_pipeline_source(app).is_some() {
        return app.path().app_data_dir().ok().map(|d| d.join("pipeline"));
    }
    dev_pipeline_dir()
}

/// 把只读资源里的 data-pipeline 源码复制到可写副本（按 App 版本号增量刷新）。
/// 资源包里只含源码（.py/.json/.md），不含 data/output —— 故覆盖源码不会动用户的纸上交易台账/行情库。
fn ensure_pipeline(app: &AppHandle) -> Option<PathBuf> {
    if let Ok(p) = std::env::var("SENTIO_PIPELINE_DIR") {
        let pb = PathBuf::from(p);
        if pb.join("run_all.py").exists() {
            return Some(pb);
        }
    }
    let Some(src) = bundled_pipeline_source(app) else {
        // 非内置发布态 → 开发态原地源码。
        return dev_pipeline_dir();
    };
    let dst = app.path().app_data_dir().ok()?.join("pipeline");
    let ver = app.package_info().version.to_string();
    let stamp = dst.join(".pipeline_version");
    let fresh = dst.join("run_all.py").exists()
        && fs::read_to_string(&stamp).map(|v| v.trim() == ver).unwrap_or(false);
    if !fresh {
        let _ = fs::create_dir_all(&dst);
        if let Err(e) = copy_pipeline_source(&src, &dst) {
            eprintln!("[sentio] 复制 data-pipeline 到可写目录失败: {e}");
            return None;
        }
        let _ = fs::write(&stamp, &ver);
    }
    Some(dst)
}

/// 复制源码（覆盖同名文件），跳过 __pycache__ / data / output / 缓存等运行期产物。
fn copy_pipeline_source(src: &Path, dst: &Path) -> std::io::Result<()> {
    for entry in WalkDir::new(src).into_iter().flatten() {
        let p = entry.path();
        let rel = match p.strip_prefix(src) {
            Ok(r) => r,
            Err(_) => continue,
        };
        if rel.as_os_str().is_empty() {
            continue;
        }
        // 跳过运行期产物/缓存目录，避免覆盖用户数据，也减小复制量。
        let skip = rel.components().any(|c| {
            matches!(
                c.as_os_str().to_str(),
                Some("__pycache__") | Some("data") | Some("output") | Some(".git")
            )
        });
        if skip {
            continue;
        }
        let target = dst.join(rel);
        if entry.file_type().is_dir() {
            fs::create_dir_all(&target)?;
        } else if entry.file_type().is_file() {
            if let Some(parent) = target.parent() {
                fs::create_dir_all(parent)?;
            }
            fs::copy(p, &target)?; // 覆盖：随 App 升级刷新脚本
        }
    }
    Ok(())
}

/// 脚本写出的前端 JSON 目录（与 Python 内 `BASE.parent/polaris-app/public/sentio` 一致）。
/// 打包态 = app-data/polaris-app/public/sentio；开发态 = 仓库 polaris-app/public/sentio。
fn front_dir(app: &AppHandle) -> Option<PathBuf> {
    let work = pipeline_work_dir(app)?;
    Some(work.parent()?.join("polaris-app").join("public").join("sentio"))
}

// ───────────────────────── 进度估算 ─────────────────────────

/// 粗略进度：从形如 "[12/32]" 的行里抽 i/n 估算 0..=80%，回测/完成阶段补到 90/100。
fn estimate_pct(line: &str) -> i32 {
    if line.contains("立即检查完成") || line.contains("策略完成") {
        return 100;
    }
    if line.contains("回测中") {
        return 88;
    }
    if let Some(start) = line.find('[') {
        if let Some(end) = line[start..].find(']') {
            let inner = &line[start + 1..start + end];
            if let Some((a, b)) = inner.split_once('/') {
                if let (Ok(i), Ok(n)) = (a.trim().parse::<f32>(), b.trim().parse::<f32>()) {
                    if n > 0.0 {
                        // 采集占前 45%，策略取价占 45%~85%；这里统一映射到 5..=85
                        return (5.0 + (i / n) * 80.0).round() as i32;
                    }
                }
            }
        }
    }
    -1
}

/// 通用：spawn data-pipeline 下某脚本，逐行 stdout/stderr 作 `{prefix}:progress` 事件上报，
/// 结束 emit `{prefix}:done`。两个「检查」命令(sentio_run/fib_run)共用，避免重复。
fn spawn_pipeline(
    app: AppHandle,
    script: &'static str,
    extra_args: Vec<String>,
    prefix: &'static str,
    done_msg: &'static str,
    ai_llm: bool,
) -> Result<String, String> {
    if RUNNING.swap(true, Ordering::SeqCst) {
        return Err("已有一次检查在进行中，请稍候".into());
    }
    // 内置发布态：把脚本复制到可写副本；开发态：仓库源码原地。
    let dir = match ensure_pipeline(&app) {
        Some(d) => d,
        None => {
            RUNNING.store(false, Ordering::SeqCst);
            return Err("未找到 data-pipeline（安装包资源缺失或仓库结构异常）".into());
        }
    };
    let python = match resolve_python(&app) {
        Some(p) => p,
        None => {
            RUNNING.store(false, Ordering::SeqCst);
            return Err("未找到内置 Python 运行时（安装包 resources/pyruntime 缺失，且系统也未装 Python）".into());
        }
    };
    let ev_prog = format!("{prefix}:progress");
    let ev_done = format!("{prefix}:done");

    std::thread::spawn(move || {
        let _guard = RunGuard;
        let mut cmd = Command::new(&python);
        cmd.arg(script);
        for a in &extra_args {
            cmd.arg(a);
        }
        cmd.current_dir(&dir)
            .env("PYTHONIOENCODING", "utf-8")
            .env("PYTHONUTF8", "1")
            // 脚本可能从只读资源被复制后仍触发 .pyc 写入；禁掉避免只读目录告警。
            .env("PYTHONDONTWRITEBYTECODE", "1")
            .stdout(Stdio::piped())
            .stderr(Stdio::piped());

        // ── 让左下角「供应商坞」选中的 API 流到管线的 AI 排雷层(ai_veto.py 的 `claude -p`)──
        // ① CLAUDE_CONFIG_DIR 钉到 App 私有目录 ~/ZhiTouGu/.claude —— 与 chat.rs 同款双保险:
        //    切到哪家 API(MiniMax/DeepSeek/自定义端点…), pipeline 里的 claude 就用哪家, 不串全局 ~/.claude,
        //    也不依赖 provider::init 的进程 env 时序(显式喂更确定)。
        // ② CLAUDE_CLI 注入解析出的 claude 真实路径 —— 顶掉 ai_veto.py 里写死的装机特定路径
        //    (C:\Users\mi\.local\bin\claude.cmd), 让任何安装环境都能找到 claude。
        // ③ ai_llm=true 时开 SENTIO_AI_LLM, 让 AI 深度研判真正调用当前 API(默认关, 省 token/时延)。
        if let Some(cfg_dir) = crate::provider::app_claude_config_dir() {
            cmd.env("CLAUDE_CONFIG_DIR", &cfg_dir);
        }
        if let Some(exe) = crate::doctor::resolve_claude_exe() {
            cmd.env("CLAUDE_CLI", exe);
        }
        if ai_llm {
            cmd.env("SENTIO_AI_LLM", "1");
            // 交互式按钮路径上限 3 只 LLM 研判, 把单次检查的额外时延/成本控住(90s/只超时兜底)。
            if std::env::var_os("SENTIO_AI_MAX").is_none() {
                cmd.env("SENTIO_AI_MAX", "3");
            }
        }
        no_window(&mut cmd);

        let mut child = match cmd.spawn() {
            Ok(c) => c,
            Err(e) => {
                let _ = app.emit(
                    &ev_done,
                    DoneEvent { ok: false, code: -1, message: format!("启动 python 失败: {e}") },
                );
                return;
            }
        };

        // stderr 单独线程透传（策略 log 走 stdout，stderr 多为告警）。
        if let Some(err) = child.stderr.take() {
            let app2 = app.clone();
            let ev2 = ev_prog.clone();
            std::thread::spawn(move || {
                let reader = BufReader::new(err);
                for line in reader.lines().map_while(Result::ok) {
                    if line.trim().is_empty() {
                        continue;
                    }
                    let pct = estimate_pct(&line);
                    let _ = app2.emit(&ev2, ProgressEvent { line, pct });
                }
            });
        }

        if let Some(out) = child.stdout.take() {
            let reader = BufReader::new(out);
            for line in reader.lines().map_while(Result::ok) {
                if line.trim().is_empty() {
                    continue;
                }
                let pct = estimate_pct(&line);
                let _ = app.emit(&ev_prog, ProgressEvent { line, pct });
            }
        }

        match child.wait() {
            Ok(s) => {
                let code = s.code().unwrap_or(-1);
                let ok = s.success();
                let _ = app.emit(
                    &ev_done,
                    DoneEvent {
                        ok,
                        code,
                        message: if ok {
                            done_msg.into()
                        } else {
                            format!("检查异常结束（退出码 {code}）")
                        },
                    },
                );
            }
            Err(e) => {
                let _ = app.emit(
                    &ev_done,
                    DoneEvent { ok: false, code: -1, message: format!("等待进程失败: {e}") },
                );
            }
        }
    });

    Ok("started".into())
}

/// 「立即检查」：跑采集 + 多因子策略 + 回测。`codes` 为空 = 全宇宙。
/// 立即返回 "started"，进度/结果走 `sentio:progress` / `sentio:done` 事件。
#[tauri::command]
pub async fn sentio_run(
    app: AppHandle,
    codes: Option<Vec<String>>,
    ai_llm: Option<bool>,
) -> Result<String, String> {
    let codes = codes.unwrap_or_default();
    spawn_pipeline(app, "run_all.py", codes, "sentio", "检查完成，数据已更新", ai_llm.unwrap_or(false))
}

/// 「斐波检查」：跑斐波那契趋势引擎（取价 + 事件回测 + 参数寻优 + 今日选股）。
/// `codes` 为空 = 全宇宙；进度/结果走 `fib:progress` / `fib:done` 事件。
#[tauri::command]
pub async fn fib_run(
    app: AppHandle,
    codes: Option<Vec<String>>,
    ai_llm: Option<bool>,
) -> Result<String, String> {
    let codes = codes.unwrap_or_default();
    spawn_pipeline(app, "run_fib.py", codes, "fib", "斐波那契选股完成，数据已更新", ai_llm.unwrap_or(false))
}

/// 读取脚本产出的前端 JSON（打包态在 app-data，开发态在仓库 public/sentio）。
/// 前端 `fetch('/sentio/x.json')` 在打包态只能读到安装包里的旧副本，故改走本命令读可写目录的最新产物。
/// 仅放行已知文件名，杜绝路径穿越。
#[tauri::command]
pub fn sentio_read(app: AppHandle, name: String) -> Option<String> {
    const ALLOW: &[&str] = &[
        "board.json",
        "sentiment_latest.json",
        "strategy.json",
        "fib_strategy.json",
        "ai_veto.json",
        "monitor_status.json",
    ];
    if !ALLOW.contains(&name.as_str()) {
        return None;
    }
    let f = front_dir(&app)?.join(&name);
    fs::read_to_string(f).ok()
}

/// 跑完务必清掉单飞标志（即便线程 panic / 提前 return）。
struct RunGuard;
impl Drop for RunGuard {
    fn drop(&mut self) {
        RUNNING.store(false, Ordering::SeqCst);
    }
}
