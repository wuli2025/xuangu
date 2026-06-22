# -*- coding: utf-8 -*-
"""
P2-C · 候选质量排序(优中选优)A/B —— 在广宇宙上找回 edge
═══════════════════════════════════════════════════════════════════════════════
P2-A 发现:800 只广宇宙诚实但 edge 薄(逐笔 +0.38R)。32 龙头 edge 强(+1.48R)却是幸存者偏差。
本脚本验证一条「中间路」:在广宇宙上,只交易「自身历史趋势表现最强」的子集——
但**用训练窗的个股 edge 选股、只在紧随的测试窗交易**(walk-forward 选股版),
杜绝「事后挑赢家」。看 OOS 收益能否随质量门槛上升而回升 → 找最佳集中度。

口径:train 12月→test 6月滚动;每窗按个股在训练窗的「期望R(要求≥MIN_TR笔)」排序,
取 Top-Q 只,只收这些股在测试窗的交易作 OOS。对比不同 Q(含全宇宙)。

数据走 P2-B 增量库(datastore,本地秒读)。用法:python quality_ab.py
"""
import sys
import json
import datetime as dt

import numpy as np
import pandas as pd

import fib_scan as fs
import datastore as ds
from fib_engine import FibConfig, simulate, summarize_trades

TRAIN_M, TEST_M = 12, 6
MIN_TR = 3                 # 训练窗个股最少交易数才纳入排序
Q_LEVELS = [40, 80, 160, 0]   # Top-Q 只(0=全宇宙基线)


def log(m):
    print(f"[{dt.datetime.now():%H:%M:%S}] {m}", flush=True)


def _ts(t):
    return pd.Timestamp(t.entry_date)


def stock_expectancy(trades, lo, hi):
    """个股在 [lo,hi) 窗内的期望R(交易不足返回 None)。"""
    sub = [t for t in trades if lo <= _ts(t) < hi]
    if len(sub) < MIN_TR:
        return None, 0
    return float(np.mean([t.r_multiple for t in sub])), len(sub)


def main():
    wl = json.loads((fs.BASE / "universe.json").read_text(encoding="utf-8"))["stocks"]
    codes = [s["code"] for s in wl]
    log(f"从增量库读 {len(codes)} 只(本地秒读)…")
    con = ds._con()
    dfs = {}
    try:
        for c in codes:
            try:
                df = ds.get_hist(c, update=False, con=con)
                if len(df) >= 80:
                    dfs[c] = df
            except Exception:
                pass
    finally:
        con.close()
    log(f"可用 {len(dfs)} 只")
    if len(dfs) < 30:
        log("数据不足,退出(先 python datastore.py migrate)")
        return

    cfg = FibConfig()
    log("逐股 simulate(全历史交易)…")
    trades_by_stock = {c: simulate(df, cfg, c) for c, df in dfs.items()}
    all_dates = [_ts(t) for tr in trades_by_stock.values() for t in tr]
    start, end = min(all_dates), max(all_dates)

    # 滚动窗口边界
    windows = []
    cursor = start + pd.DateOffset(months=TRAIN_M)
    while cursor < end:
        windows.append((cursor - pd.DateOffset(months=TRAIN_M), cursor,
                        cursor, cursor + pd.DateOffset(months=TEST_M)))
        cursor += pd.DateOffset(months=TEST_M)

    log(f"walk-forward 选股:{len(windows)} 窗 · 扫描 Q={Q_LEVELS}")
    results = {}
    for Q in Q_LEVELS:
        oos = []
        picked_counts = []
        for (tr_lo, tr_hi, te_lo, te_hi) in windows:
            # 训练窗按个股期望R 排序
            ranked = []
            for c, tr in trades_by_stock.items():
                er, n = stock_expectancy(tr, tr_lo, tr_hi)
                if er is not None:
                    ranked.append((c, er))
            ranked.sort(key=lambda x: -x[1])
            chosen = [c for c, _ in ranked] if Q == 0 else [c for c, _ in ranked[:Q]]
            picked_counts.append(len(chosen))
            # 测试窗只收选中股的交易
            for c in chosen:
                oos.extend([t for t in trades_by_stock[c] if te_lo <= _ts(t) < te_hi])
        st = summarize_trades(oos)
        m, _ = fs.portfolio_backtest(dfs, cfg, trades=oos)
        results[Q] = (st, m, int(np.mean(picked_counts)) if picked_counts else 0)

    print("\n" + "═" * 92)
    print(f"候选质量排序 A/B(walk-forward 选股,无未来函数)· 宇宙 {len(dfs)} 只 · {start.date()}→{end.date()}")
    print("─" * 92)
    print(f"{'集中度':<16}{'OOS交易':>8}{'胜率':>7}{'期望R':>8}{'PF':>7}{'组合CAGR':>10}{'回撤':>8}{'夏普':>7}")
    print("─" * 92)
    best = None
    for Q in Q_LEVELS:
        st, m, avgn = results[Q]
        tag = f"全宇宙(~{avgn})" if Q == 0 else f"Top{Q}(每窗{avgn})"
        if not st or not m:
            print(f"{tag:<16}  (数据不足)")
            continue
        print(f"{tag:<16}{st['trades']:>8}{st['win_rate']:>6.1f}%{st['expectancy_r']:>8.3f}"
              f"{(st['profit_factor'] or 0):>7.2f}{m['cagr']:>9.1f}%{m['max_drawdown']:>7.1f}%{m['sharpe']:>7.2f}")
        if Q != 0 and (best is None or m["sharpe"] > best[1]):
            best = (Q, m["sharpe"], m, st)
    print("═" * 92)

    b_st, b_m, _ = results[0]               # 全宇宙基线
    if best and b_st and b_m:
        Q, _, bm, bst = best                # 集中子集里最优的一档
        d_cagr = bm["cagr"] - b_m["cagr"]
        d_sh = bm["sharpe"] - b_m["sharpe"]
        print(f"集中子集最优:Top{Q} · CAGR {bm['cagr']}%(全宇宙 {b_m['cagr']}%,{d_cagr:+.1f}pp)· "
              f"夏普 {bm['sharpe']}(全宇宙 {b_m['sharpe']},Δ{d_sh:+.2f})")
        if d_sh > 0.05 or d_cagr > 3:
            print(f"结论:✅ 优中选优有效——按个股历史 edge 集中到 Top{Q} 跑赢全宇宙,且无幸存者偏差。建议接入选股。")
        else:
            print("结论:❌ 优中选优【无效】——全宇宙分散反而最优,夏普/CAGR 均高于任何集中子集。")
            print("       说明个股『历史趋势 edge 不具持续性』:按过去业绩集中=追涨,广撒网分散已近最优。")
            print("       → 提收益不能靠『挑过去的强者』,要靠正交维度增厚 edge(多因子叠加 / AI 否决坏票 / 趋势品种过滤)。")


if __name__ == "__main__":
    main()
