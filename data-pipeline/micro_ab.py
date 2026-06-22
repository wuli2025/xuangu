# -*- coding: utf-8 -*-
"""
P1-C 验证:A股微结构修正 A/B
─────────────────────────────────────────────────────────────────────
同一宇宙、同一配置,对比 a_share_rules 开/关:
  关 = 旧的乐观回测(可当日买卖、涨跌停照常成交)
  开 = T+1不可当日卖 + 涨停一字板买不进(跳过) + 跌停一字板卖不出(顺延打开板成交)
量化「可落地折价」:微结构修正后 edge 还剩多少。

用法:python micro_ab.py [代码...]
"""
import sys
import json
import datetime as dt

import fib_scan as fs
from fib_engine import FibConfig, simulate, summarize_trades


def line(tag, st, m):
    s = f"  {tag:<16}"
    if st:
        s += (f"交易{st['trades']:>4} 胜率{st['win_rate']:>5.1f}% 盈亏比{st['payoff_ratio']:>6} "
              f"期望R{st['expectancy_r']:>7.3f} PF{st['profit_factor']:>6}")
    if m:
        s += f"  | 组合CAGR{m['cagr']:>6.1f}% 回撤{m['max_drawdown']:>6.1f}% 夏普{m['sharpe']:>5.2f}"
    return s


def main():
    args = [a for a in sys.argv[1:] if a.strip()]
    wl = json.loads(fs.WATCHLIST.read_text(encoding="utf-8"))["stocks"]
    if args:
        wl = [s for s in wl if s["code"] in args]
    print(f"[{dt.datetime.now():%H:%M:%S}] 取价 {len(wl)} 只(带缓存)…", flush=True)
    dfs = {}
    for s in wl:
        try:
            df = fs.fetch_hist(s["code"])
            if len(df) >= 80:
                dfs[s["code"]] = df
        except Exception:
            pass
    print(f"  可用 {len(dfs)} 只", flush=True)
    if len(dfs) < 5:
        return

    res = {}
    delayed_total = up_skipped_hint = 0
    for tag, rules in [("关·乐观回测", False), ("开·A股微结构", True)]:
        cfg = FibConfig(a_share_rules=rules)
        trades = []
        for code, df in dfs.items():
            trades.extend(simulate(df, cfg, code))
        st = summarize_trades(trades)
        m, _ = fs.portfolio_backtest(dfs, cfg)
        res[tag] = (st, m)
        if rules:
            delayed_total = sum(1 for t in trades if t.exit_reason.endswith("_delayed"))

    print("\n" + "═" * 96)
    print(f"A股微结构 A/B · 宇宙 {len(dfs)} 只 · 配置 {FibConfig().label()}")
    print("─" * 96)
    for tag in ("关·乐观回测", "开·A股微结构"):
        st, m = res[tag]
        print(line(tag, st, m))
    print("─" * 96)
    a_st, a_m = res["关·乐观回测"]
    b_st, b_m = res["开·A股微结构"]
    if a_st and b_st and a_m and b_m:
        print(f"可落地折价:期望R {a_st['expectancy_r']}→{b_st['expectancy_r']} "
              f"({(b_st['expectancy_r']/a_st['expectancy_r']-1)*100:+.0f}%) · "
              f"CAGR {a_m['cagr']}%→{b_m['cagr']}% ({b_m['cagr']-a_m['cagr']:+.1f}pp) · "
              f"夏普 {a_m['sharpe']}→{b_m['sharpe']}")
        print(f"其中跌停顺延成交 {delayed_total} 笔。")
        keep = b_st['expectancy_r'] / a_st['expectancy_r'] if a_st['expectancy_r'] else 0
        if b_st['expectancy_r'] > 0.3 and keep > 0.7:
            print("结论:✅ 微结构修正后 edge 仍稳健(保留 >70% 期望R)。这才是可落地的诚实业绩。")
        elif b_st['expectancy_r'] > 0:
            print("结论:⚠ 微结构修正吃掉可观 edge,仍正但变薄。需控仓 + 避开一字板品种。")
        else:
            print("结论:❌ 微结构修正后 edge 消失,原业绩多来自不可成交的偷价,勿实盘。")
    print("═" * 96)


if __name__ == "__main__":
    main()
