# -*- coding: utf-8 -*-
"""
SENTIO 一键「立即检查」编排器
先跑情绪采集(collect.py) → 再跑多因子策略(strategy.py)，串成完整闭环：
  舆情温度 + 资金面  →  多因子达人评分 + 交易计划 + 组合 + 回测
前端「立即检查」按钮通过 Rust(sentio_run) 调起本脚本，逐行 stdout 作进度上报。

用法：python run_all.py            # 全宇宙
     python run_all.py 600519     # 指定代码（横截面会退化，建议全量）
"""
import sys
import time
import datetime as dt
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))


def banner(msg):
    print(f"\n===== {msg} =====", flush=True)


def main():
    codes = [a for a in sys.argv[1:] if a.strip()]
    t0 = time.time()
    print(f"[{dt.datetime.now():%H:%M:%S}] 立即检查启动 · 阶段 1/2 情绪采集", flush=True)

    banner("阶段 1/2 · 舆情情绪采集")
    import collect
    sys.argv = ["collect.py", *codes]
    try:
        collect.main()
    except Exception as e:
        print(f"[WARN] 采集阶段异常（策略将用上次情绪数据继续）：{type(e).__name__}: {e}", flush=True)

    banner("阶段 2/2 · 多因子策略 + 回测")
    print(f"[{dt.datetime.now():%H:%M:%S}] 进入阶段 2/2 策略与回测", flush=True)
    import strategy
    sys.argv = ["strategy.py", *codes]
    strategy.main()

    print(f"\n[{dt.datetime.now():%H:%M:%S}] 立即检查完成 · 用时 {time.time()-t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
