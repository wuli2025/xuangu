# -*- coding: utf-8 -*-
"""
SENTIO · 斐波那契趋势选股 一键编排（前端「斐波检查」/ 计划任务 都走这条）
先(可选)刷新情绪 → 跑 fib_scan（取价+回测+寻优+今日选股）→ 产出 fib_strategy.json。
逐行 stdout 作进度上报，Rust(fib_run) 透传给前端。

用法：
  python run_fib.py                 # 全宇宙：含参数寻优
  python run_fib.py --quick         # 跳过寻优(默认配置)，更快，适合每日盘后调度
  python run_fib.py 600519 300308   # 指定代码
"""
import sys
import time
import datetime as dt
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))


def main():
    args = sys.argv[1:]
    t0 = time.time()
    print(f"[{dt.datetime.now():%H:%M:%S}] 斐波那契趋势选股启动", flush=True)
    print("===== 斐波那契趋势引擎 · 取价 + 回测 + 寻优 + 今日选股 =====", flush=True)
    import fib_scan
    sys.argv = ["fib_scan.py", *args]
    fib_scan.main()
    print(f"\n[{dt.datetime.now():%H:%M:%S}] 斐波那契选股完成 · 用时 {time.time()-t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
