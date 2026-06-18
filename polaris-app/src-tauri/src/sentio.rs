//! 板块 · SENTIO 选股达人「立即检查」
//!
//! 前端点「立即检查」→ 本命令 spawn data-pipeline 的 run_all.py（采集情绪 + 多因子策略 + 回测），
//! 逐行 stdout 作进度事件 `sentio:progress` 上报，结束 emit `sentio:done` / `sentio:error`。
//! 产物 board.json / sentiment_latest.json / strategy.json 落到 polaris-app/public/sentio/，
//! 前端三屏 + 建议策略页 fetch 即可看到最新结果。
//!
//! 仅桌面端：需要本机 python 环境（akshare/pandas）。Docker/web 外壳不挂此命令。

use serde::Serialize;
use std::io::{BufRead, BufReader};
use std::path::PathBuf;
use std::process::{Command, Stdio};
use std::sync::atomic::{AtomicBool, Ordering};
use tauri::{AppHandle, Emitter};

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

/// 定位 data-pipeline 目录：
/// 1) 环境变量 SENTIO_PIPELINE_DIR 覆盖；
/// 2) 开发态：src-tauri 的上两级（仓库根）下的 data-pipeline；
/// 3) 当前工作目录附近兜底。
fn pipeline_dir() -> Option<PathBuf> {
    if let Ok(p) = std::env::var("SENTIO_PIPELINE_DIR") {
        let pb = PathBuf::from(p);
        if pb.join("run_all.py").exists() {
            return Some(pb);
        }
    }
    let mut cands: Vec<PathBuf> = Vec::new();
    // CARGO_MANIFEST_DIR = .../polaris-app/src-tauri → 仓库根 = 上两级
    let manifest = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    if let Some(repo) = manifest.parent().and_then(|p| p.parent()) {
        cands.push(repo.join("data-pipeline"));
    }
    if let Ok(cwd) = std::env::current_dir() {
        cands.push(cwd.join("data-pipeline"));
        if let Some(p) = cwd.parent() {
            cands.push(p.join("data-pipeline"));
        }
    }
    cands.into_iter().find(|p| p.join("run_all.py").exists())
}

/// 解析可用的 python 解释器（python / python3 / py）。
fn resolve_python() -> Option<String> {
    for cand in ["python", "python3", "py"] {
        let mut c = Command::new(cand);
        c.arg("--version");
        no_window(&mut c);
        if let Ok(out) = c.output() {
            if out.status.success() {
                return Some(cand.to_string());
            }
        }
    }
    None
}

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
) -> Result<String, String> {
    if RUNNING.swap(true, Ordering::SeqCst) {
        return Err("已有一次检查在进行中，请稍候".into());
    }
    let dir = match pipeline_dir() {
        Some(d) => d,
        None => {
            RUNNING.store(false, Ordering::SeqCst);
            return Err("未找到 data-pipeline 目录（设 SENTIO_PIPELINE_DIR 或确认仓库结构）".into());
        }
    };
    let python = match resolve_python() {
        Some(p) => p,
        None => {
            RUNNING.store(false, Ordering::SeqCst);
            return Err("未检测到 python（需安装 Python 3 + akshare/pandas）".into());
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
            .stdout(Stdio::piped())
            .stderr(Stdio::piped());
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
pub async fn sentio_run(app: AppHandle, codes: Option<Vec<String>>) -> Result<String, String> {
    let codes = codes.unwrap_or_default();
    spawn_pipeline(app, "run_all.py", codes, "sentio", "检查完成，数据已更新")
}

/// 「斐波检查」：跑斐波那契趋势引擎（取价 + 事件回测 + 参数寻优 + 今日选股）。
/// `codes` 为空 = 全宇宙；进度/结果走 `fib:progress` / `fib:done` 事件。
#[tauri::command]
pub async fn fib_run(app: AppHandle, codes: Option<Vec<String>>) -> Result<String, String> {
    let codes = codes.unwrap_or_default();
    spawn_pipeline(app, "run_fib.py", codes, "fib", "斐波那契选股完成，数据已更新")
}

/// 跑完务必清掉单飞标志（即便线程 panic / 提前 return）。
struct RunGuard;
impl Drop for RunGuard {
    fn drop(&mut self) {
        RUNNING.store(false, Ordering::SeqCst);
    }
}
