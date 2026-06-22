# -*- coding: utf-8 -*-
"""
P1-A 验证:市场态势闸 A/B 对比
─────────────────────────────────────────────────────────────────────
同一批股票、同一配置,组合层回测跑两遍:
  A) 不启用 regime 闸(基线,旧行为)
  B) 启用 regime 闸(风险关停跳过新开仓 / 半仓减半)
对比 CAGR / 最大回撤 / 夏普 / 超额,诚实判断 regime 闸是否提升风险调整后收益。

用法:python regime_ab.py            # 全 watchlist
     python regime_ab.py 600519 ... # 指定子集(更快)
"""
import sys
import datetime as dt

import fib_scan as fs
import regime as rg
from fib_engine import FibConfig


def fmt(m):
    if not m:
        return "  (回测数据不足)"
    return (f"  总收益 {m['total_return']:>7.1f}%  CAGR {m['cagr']:>6.1f}%  "
            f"回撤 {m['max_drawdown']:>6.1f}%  夏普 {m['sharpe']:>5.2f}  "
            f"超额基准 {m['excess']:>7.1f}%")


def main():
    args = [a for a in sys.argv[1:] if a.strip()]
    import json
    wl = json.loads(fs.WATCHLIST.read_text(encoding="utf-8"))["stocks"]
    if args:
        wl = [s for s in wl if s["code"] in args]

    print(f"[{dt.datetime.now():%H:%M:%S}] 取价 {len(wl)} 只(新浪日线~3年, 带当日缓存)…", flush=True)
    dfs = {}
    for i, s in enumerate(wl):
        try:
            df = fs.fetch_hist(s["code"])
            if len(df) >= 80:
                dfs[s["code"]] = df
        except Exception as e:
            print(f"  {s['code']} 取价失败 {type(e).__name__}", flush=True)
    print(f"  可用 {len(dfs)} 只", flush=True)
    if len(dfs) < 5:
        print("数据不足,退出")
        return

    cfg = FibConfig()   # 默认配置,保证 A/B 唯一变量是 regime 闸

    print(f"[{dt.datetime.now():%H:%M:%S}] 构建市场态势序列(沪深300)…", flush=True)
    idx = rg.fetch_index()

    # 扫描多种敞口映射 (bear, neutral, bull),找真正提升风险调整后收益的那一档
    variants = [
        ("基线·无闸",          None),
        ("激进闸 0/0.5/1",     (0.0, 0.5, 1.0)),   # 老设计:一刀切,实测有害
        ("只砍深熊 0/1/1",     (0.0, 1.0, 1.0)),   # 仅真熊市停手,震荡不动
        ("熊市半仓 0.5/1/1",   (0.5, 1.0, 1.0)),
        ("熊市七成 0.7/1/1",   (0.7, 1.0, 1.0)),   # 默认
        ("轻度择时 0.7/0.85/1", (0.7, 0.85, 1.0)),
    ]

    print(f"\n[{dt.datetime.now():%H:%M:%S}] 回测中(扫描 {len(variants)} 档映射)…", flush=True)
    rows = []
    for name, lv in variants:
        rexp = None if lv is None else rg.regime_series(idx, levels=lv)
        m, _ = fs.portfolio_backtest(dfs, cfg, regime_exp=rexp)
        rows.append((name, m))

    base = rows[0][1]
    print("\n" + "═" * 88)
    print(f"配置:{cfg.label()} · 宇宙 {len(dfs)} 只 · 样本 {base['start']}→{base['end']}")
    print("─" * 88)
    print(f"{'映射(熊/震/牛)':<22}{'CAGR':>8}{'回撤':>8}{'夏普':>7}{'超额':>9}   Δ夏普")
    print("─" * 88)
    best = None
    for name, m in rows:
        if not m:
            print(f"{name:<22}  (数据不足)")
            continue
        d_sharpe = m["sharpe"] - base["sharpe"]
        mark = ""
        if name != "基线·无闸":
            if best is None or m["sharpe"] > best[1]["sharpe"]:
                best = (name, m)
        print(f"{name:<22}{m['cagr']:>7.1f}%{m['max_drawdown']:>7.1f}%{m['sharpe']:>7.2f}"
              f"{m['excess']:>8.1f}%   {d_sharpe:+.2f}{mark}")
    print("═" * 88)

    if best:
        bn, bm = best
        d_sh = bm["sharpe"] - base["sharpe"]
        d_mdd = bm["max_drawdown"] - base["max_drawdown"]
        d_cagr = bm["cagr"] - base["cagr"]
        print(f"最佳变体:【{bn}】 夏普 {bm['sharpe']:.2f}(Δ{d_sh:+.2f}) · "
              f"回撤 {bm['max_drawdown']:.1f}%(Δ{d_mdd:+.1f}pp) · CAGR {bm['cagr']:.1f}%(Δ{d_cagr:+.1f}pp)")
        if d_sh > 0.03:
            print(f"结论:✅ 启用【{bn}】——风险调整后收益优于基线。设为 regime 默认映射。")
        elif d_mdd > 0.5 and d_cagr > -3:
            print(f"结论:✅ 启用【{bn}】——回撤变浅而收益基本保住,risk-adjusted 更优。")
        else:
            print("结论:⚠ 本样本期(2023-2026 多为龙头单边上行)任何指数择时都难超越满仓。"
                  "regime 闸的真正价值在熊市样本——保留为『可配置防御层』,默认用最温和档,"
                  "实盘以『破位停手』为主要用途,而非牛市里减仓。")


if __name__ == "__main__":
    main()
