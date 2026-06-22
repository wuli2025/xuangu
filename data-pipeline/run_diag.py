# -*- coding: utf-8 -*-
"""
SENTIO · 自选诊断 一键编排（前端「自选诊断」按钮 / 计划任务 走这条）
diagnose(取真实行情 + 多策略诊断 + 操作时机/价位 + 真实性戳) → ai_veto(对诊断到的票做新闻排雷)。
逐行 stdout 作进度上报，Rust(diag_run) 透传给前端。

用法：
  python run_diag.py 600519 300308     # 诊断指定代码（前端把你输入框里的代码透传进来）
  python run_diag.py                    # 诊断 my_watchlist.json
"""
import sys
import time
import datetime as dt
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))


def _stamp(msg):
    print(f"[{dt.datetime.now():%H:%M:%S}] {msg}", flush=True)


def main():
    args = [a for a in sys.argv[1:] if a.strip()]
    t0 = time.time()
    _stamp("自选诊断启动")
    print("===== ① 自选诊断 · 真实行情 + 多策略 + 操作时机/价位 =====", flush=True)
    import diagnose
    sys.argv = ["diagnose.py", *args]
    diagnose.main()

    # ── 接力：对诊断到的票做真实新闻排雷（与斐波同款，可选 LLM 深研）──
    # 没显式传代码时，从刚产出的 diagnose.json 取实际诊断到的代码喂给排雷层。
    print("\n===== ② AI 催化剂排雷(基于真实新闻) =====", flush=True)
    try:
        import json
        codes = list(args)
        if not codes:
            dj = BASE / "output" / "diagnose.json"
            if dj.exists():
                data = json.loads(dj.read_text(encoding="utf-8"))
                codes = [d["code"] for d in data.get("diagnoses", []) if d.get("code") and not d.get("error")]
        import ai_veto
        sys.argv = ["ai_veto.py", *codes]
        ai_veto.main()
    except SystemExit:
        pass
    except Exception as e:
        _stamp(f"[WARN] AI排雷 跳过：{type(e).__name__}: {str(e)[:60]}")

    _stamp(f"自选诊断完成 · 用时 {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
