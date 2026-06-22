# -*- coding: utf-8 -*-
"""
SENTIO 量化系统 · 盘后总调度器 (Daily Orchestrator)
═══════════════════════════════════════════════════════════════════════════════
把整条工业级流水线串成一条命令,交易日盘后(15:30 后)跑一次即完成全闭环:

  ① 增量更新行情(datastore)——只补当天新增,秒级
  ② 斐波趋势选股 + 样本外验证(fib_scan)——产出今日候选 + 诚实 OOS 业绩
  ③ AI 催化剂排雷(ai_veto)——对候选拉真实新闻做红旗否决(防幻觉)
  ④ 纸上交易推进(paper_trade)——盯市离场 / 信号进场(避开 AI 否决)/ 风控熔断 / 记账
  ⑤ 健康监控(monitor)——四层状态面板 + status.json

任一环失败不阻断后续(尽力而为 + 告警),最后由 monitor 汇总系统健康度。

用法:
  $env:SENTIO_WATCHLIST="universe.json"   # 跑中证800大宇宙(否则默认精选 watchlist)
  python run_daily.py                      # 全流程
  python run_daily.py --no-update          # 跳过行情更新(用库内现有数据)
  $env:SENTIO_AI_LLM="1"; python run_daily.py   # AI 排雷叠加 claude CLI 深研
"""
import os
import sys
import json
import time
import datetime as dt
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))


def banner(msg):
    print(f"\n{'='*64}\n  {msg}\n{'='*64}", flush=True)


def step(name, fn):
    t0 = time.time()
    try:
        fn()
        print(f"  ✓ {name} 完成 · {time.time()-t0:.1f}s", flush=True)
        return True
    except Exception as e:
        print(f"  ✗ {name} 失败(不阻断后续):{type(e).__name__}: {str(e)[:60]}", flush=True)
        return False


def main():
    args = sys.argv[1:]
    no_update = "--no-update" in args
    t0 = time.time()
    wl = os.environ.get("SENTIO_WATCHLIST", "watchlist.json")
    print(f"[{dt.datetime.now():%H:%M:%S}] SENTIO 盘后总调度 · 宇宙文件 {wl}", flush=True)

    # ① 增量行情更新
    if not no_update:
        banner("① 增量更新行情(datastore)")
        def _update():
            import datastore as ds
            codes = [s["code"] for s in json.loads((BASE / wl).read_text(encoding="utf-8"))["stocks"]]
            r = ds.update_many(codes)
            print(f"  更新 {len(r['ok'])} 成功 / {len(r['fail'])} 失败", flush=True)
        step("行情更新", _update)

    # ② 斐波选股 + OOS
    banner("② 斐波趋势选股 + 样本外验证(fib_scan)")
    def _scan():
        import fib_scan
        fib_scan.main()
    step("选股回测", _scan)

    # ③ AI 排雷
    banner("③ AI 催化剂排雷(ai_veto)")
    def _veto():
        import importlib, ai_veto
        importlib.reload(ai_veto)
        sys.argv = ["ai_veto.py"]
        ai_veto.main()
    step("AI排雷", _veto)

    # ④ 纸上交易推进
    banner("④ 纸上交易推进(paper_trade)")
    def _paper():
        import importlib, paper_trade
        importlib.reload(paper_trade)
        paper_trade.run()
    step("纸上交易", _paper)

    # ⑤ 健康监控
    banner("⑤ 健康监控(monitor)")
    def _mon():
        import importlib, monitor
        importlib.reload(monitor)
        monitor.main()
    step("健康面板", _mon)

    print(f"\n[{dt.datetime.now():%H:%M:%S}] 盘后总调度完成 · 总用时 {time.time()-t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
