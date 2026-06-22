# -*- coding: utf-8 -*-
"""
SENTIO · 斐波那契趋势选股 一键编排（前端「斐波检查」/ 计划任务 都走这条）
fib_scan(取价+回测+寻优+今日选股) → ai_veto(AI新闻排雷) → paper_trade(纸上成交) → monitor(健康面板)。
一次按钮产出前端要的全部 JSON：fib_strategy / ai_veto / monitor_status / paper_ledger。
逐行 stdout 作进度上报，Rust(fib_run) 透传给前端。

用法：
  python run_fib.py                 # 全宇宙：含参数寻优 + 后续接力
  python run_fib.py --quick         # 跳过寻优(默认配置)，更快，适合每日盘后调度
  python run_fib.py 600519 300308   # 指定代码
"""
import sys
import time
import datetime as dt
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))


def _stamp(msg):
    print(f"[{dt.datetime.now():%H:%M:%S}] {msg}", flush=True)


def _step(label, fn):
    """跑一个接力步骤，失败不阻断后续（前端整体仍刷新）。"""
    try:
        fn()
        return True
    except Exception as e:
        _stamp(f"[WARN] {label} 跳过：{type(e).__name__}: {str(e)[:60]}")
        return False


def main():
    args = sys.argv[1:]
    t0 = time.time()
    _stamp("斐波那契趋势选股启动")
    print("===== ① 斐波趋势引擎 · 取价 + 回测 + 寻优 + 今日选股 =====", flush=True)
    import fib_scan
    sys.argv = ["fib_scan.py", *args]
    fib_scan.main()

    # ── 接力：让前端的 AI排雷徽章 / 健康灯 / 账户随「斐波检查」一并刷新 ──
    print("\n===== ② AI 催化剂排雷(基于真实新闻) =====", flush=True)
    def _veto():
        import ai_veto
        sys.argv = ["ai_veto.py"]
        ai_veto.main()
    _step("AI排雷", _veto)

    print("\n===== ③ 纸上交易推进(模拟成交/风控) =====", flush=True)
    def _paper():
        import paper_trade
        paper_trade.run()
    _step("纸上交易", _paper)

    print("\n===== ④ 系统健康面板 =====", flush=True)
    def _mon():
        import monitor
        sys.argv = ["monitor.py"]
        monitor.main()
    _step("健康面板", _mon)

    _stamp(f"斐波那契选股完成 · 用时 {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
