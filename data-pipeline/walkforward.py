# -*- coding: utf-8 -*-
"""
P1-B · Walk-Forward 样本外(OOS)验证
═══════════════════════════════════════════════════════════════════════════════
工业级回测的硬门槛:证明 edge 是「样本外可复现」的,而非参数寻优的过拟合幻觉。

现有 fib_scan.grid_search 在同一段数据上「选最优参 + 报告该参业绩」= 样本内自夸。
本脚本改成滚动前进:
  ┌─ train(12月) ─┐
                  ├─ test(6月) ─┐         在 train 窗选 profit_factor 最优参,
                  └──────────────┴─ test… 只在紧随其后的 test 窗用该参 → 收 OOS 交易
  窗口按 step=test 向前滚动,拼接所有 test 窗交易 = 纯样本外业绩。

对比口径:
  • 样本内(IS):全样本上跑每个参,取最优参的池化业绩(乐观上界)
  • 样本外(OOS):上述滚动拼接(诚实业绩)
OOS 期望R/profit factor 若仍显著>0 且接近 IS → edge 稳健;若坍塌 → 是过拟合,需警惕。

用法:python walkforward.py            # 全 watchlist
     python walkforward.py 600519 ... # 子集
"""
import sys
import json
import datetime as dt

import pandas as pd

import fib_scan as fs
from fib_engine import FibConfig, simulate, summarize_trades

# 参数网格(与 grid_search 同口径:斐波系数 k × 趋势均线 m)
GRID = [(k, m) for k in (1.0, 1.618, 2.618) for m in (21, 34, 55)]
TRAIN_M = 12     # 训练窗(月)
TEST_M = 6       # 测试窗(月)= 滚动步长
MIN_TRAIN_TRADES = 12   # 训练窗最少交易数,否则回退默认参


def log(m):
    print(f"[{dt.datetime.now():%H:%M:%S}] {m}", flush=True)


def _entry_ts(t):
    return pd.Timestamp(t.entry_date)


def pooled_in_window(trades, lo, hi):
    """取 entry_date∈[lo,hi) 的交易池化统计。"""
    sub = [t for t in trades if lo <= _entry_ts(t) < hi]
    return sub, summarize_trades(sub)


def run_oos(dfs: dict, verbose: bool = False) -> dict:
    """对外:对给定 dfs 跑 walk-forward,返回 {is, oos, oos_portfolio, schedule, verdict}。
    供 fib_scan 在每日产出里附「样本内 vs 样本外」诚实对照。数据不足返回 None。"""
    if len(dfs) < 5:
        return None
    # 每个参数组只 simulate 一次,缓存全历史交易(按参分桶)
    trades_by_cfg = {}
    for (k, m) in GRID:
        cfg = FibConfig(k=k, m=m)
        tr = []
        for code, df in dfs.items():
            tr.extend(simulate(df, cfg, code))
        trades_by_cfg[(k, m)] = tr

    # 时间轴范围
    all_dates = [_entry_ts(t) for tr in trades_by_cfg.values() for t in tr]
    if not all_dates:
        return None
    start, end = min(all_dates), max(all_dates)

    # ── 滚动前进 ──
    oos_trades = []
    schedule = []
    cursor = start + pd.DateOffset(months=TRAIN_M)
    while cursor < end:
        train_lo = cursor - pd.DateOffset(months=TRAIN_M)
        train_hi = cursor
        test_lo = cursor
        test_hi = cursor + pd.DateOffset(months=TEST_M)
        # 在 train 窗为每组参算 profit_factor,选最优(要求够交易数)
        best_key, best_pf, best_er = None, -1e9, None
        for key, tr in trades_by_cfg.items():
            _, st = pooled_in_window(tr, train_lo, train_hi)
            if not st or st["trades"] < MIN_TRAIN_TRADES:
                continue
            pf = st["profit_factor"] or 0
            if pf > best_pf:
                best_pf, best_key, best_er = pf, key, st["expectancy_r"]
        if best_key is None:
            best_key = (1.618, 34)   # 训练样本不足 → 回退默认参
        # 用选中的参,收 test 窗交易作 OOS
        test_sub, _ = pooled_in_window(trades_by_cfg[best_key], test_lo, test_hi)
        oos_trades.extend(test_sub)
        schedule.append({
            "train": f"{train_lo.date()}~{train_hi.date()}",
            "test": f"{test_lo.date()}~{test_hi.date()}",
            "chosen_k": best_key[0], "chosen_m": best_key[1],
            "train_pf": round(best_pf, 2) if best_pf > -1e8 else None,
            "oos_trades": len(test_sub),
        })
        cursor = cursor + pd.DateOffset(months=TEST_M)

    # ── 样本内基准(全样本最优参,乐观上界)──
    is_best_key, is_best_pf, is_best_st = None, -1e9, None
    for key, tr in trades_by_cfg.items():
        st = summarize_trades(tr)
        if st and (st["profit_factor"] or 0) > is_best_pf:
            is_best_pf, is_best_key, is_best_st = st["profit_factor"] or 0, key, st

    oos_st = summarize_trades(oos_trades)

    # OOS 组合层权益(复用 portfolio_backtest,喂入 OOS 交易)
    oos_metrics, _ = fs.portfolio_backtest(dfs, FibConfig(), trades=oos_trades)

    # 诚实判定
    verdict = None
    if oos_st and is_best_st:
        er_oos = oos_st["expectancy_r"]
        pf_oos = oos_st["profit_factor"] or 0
        retention = (er_oos / is_best_st["expectancy_r"]) if is_best_st["expectancy_r"] else 0
        if er_oos > 0.3 and pf_oos >= 1.5:
            head = (f"✅ edge 样本外稳健:OOS 期望 +{er_oos}R、profit factor {pf_oos}"
                    f"(保留样本内 {retention*100:.0f}% 期望R)。非过拟合。")
            effective = True
        elif er_oos > 0 and pf_oos >= 1.1:
            head = (f"⚠ edge 样本外边际为正(+{er_oos}R、pf {pf_oos}),较样本内明显衰减"
                    f"(保留 {retention*100:.0f}%)。对成本敏感,需控仓。")
            effective = True
        else:
            head = f"❌ edge 样本外坍塌(期望 {er_oos}R、pf {pf_oos}),疑过拟合,勿据此实盘。"
            effective = False
        verdict = {"effective": effective, "retention_pct": round(retention * 100, 0), "headline": head}

    return {
        "window": {"train_months": TRAIN_M, "test_months": TEST_M, "step_months": TEST_M},
        "span": f"{start.date()}→{end.date()}",
        "is_best": {"k": is_best_key[0], "m": is_best_key[1], **(is_best_st or {})},
        "is_pooled": is_best_st,
        "oos_pooled": oos_st,
        "oos_portfolio": oos_metrics,
        "schedule": schedule,
        "verdict": verdict,
    }


def main():
    args = [a for a in sys.argv[1:] if a.strip()]
    wl = json.loads(fs.WATCHLIST.read_text(encoding="utf-8"))["stocks"]
    if args:
        wl = [s for s in wl if s["code"] in args]
    log(f"取价 {len(wl)} 只(带当日缓存)…")
    dfs = {}
    for s in wl:
        try:
            df = fs.fetch_hist(s["code"])
            if len(df) >= 80:
                dfs[s["code"]] = df
        except Exception:
            pass
    log(f"可用 {len(dfs)} 只 · 预跑 {len(GRID)} 组参数 + walk-forward(train{TRAIN_M}/test{TEST_M}月)…")
    res = run_oos(dfs)
    if not res:
        log("数据不足,退出")
        return

    def line(tag, st):
        if not st:
            return f"  {tag:<14} (数据不足)"
        return (f"  {tag:<14} 交易 {st['trades']:>4} · 胜率 {st['win_rate']:>5.1f}% · "
                f"盈亏比 {st['payoff_ratio']} · 期望R {st['expectancy_r']:>6.3f} · "
                f"profit factor {st['profit_factor']}")

    print("\n" + "═" * 80)
    print(f"Walk-Forward OOS 验证 · 宇宙 {len(dfs)} 只 · {res['span']}")
    print("─" * 80)
    print("滚动窗口选参轨迹:")
    print(f"  {'测试窗':<26}{'选中参(k/m)':<14}{'train_pf':>9}{'OOS笔数':>8}")
    for s in res["schedule"]:
        km = f"{s['chosen_k']}/{s['chosen_m']}"
        pf = s['train_pf'] if s['train_pf'] is not None else 0
        print(f"  {s['test']:<26}{km:<14}{pf:>9.2f}{s['oos_trades']:>8}")
    print("─" * 80)
    ib = res["is_best"]
    print(f"样本内(IS, 全样本最优参 k={ib['k']}/m={ib['m']}, 乐观上界):")
    print(line("IS-pooled", res["is_pooled"]))
    print("样本外(OOS, 滚动选参拼接, 诚实业绩):")
    print(line("OOS-pooled", res["oos_pooled"]))
    m = res["oos_portfolio"]
    if m:
        print(f"  OOS 组合:总收益 {m['total_return']}% · CAGR {m['cagr']}% · 回撤 {m['max_drawdown']}% "
              f"· 夏普 {m['sharpe']} · 超额基准 {m['excess']}%")
    print("═" * 80)
    if res["verdict"]:
        print("结论:" + res["verdict"]["headline"])


if __name__ == "__main__":
    main()
