# -*- coding: utf-8 -*-
"""
量化引擎不变量测试(零网络、确定性,合成数据)
─────────────────────────────────────────────────────────────────────
守住几条「错了就是灾难」的底线,作为改策略时的回归护栏:
  ① T+1:开启 A 股规则后,绝不允许「当日买当日卖」(exit_date==entry_date / bars==0)
  ② 无未来函数:simulate 进场永远发生在信号根之后,出场不早于进场
  ③ 涨跌停幅度按板块正确(主板10/创业板科创20/北交30)
  ④ regime 的 point-in-time:某日敞口只由该日及之前的数据决定(截断历史重算结果一致)
  ⑤ 池化统计口径:已知交易的胜率/期望R 计算正确

用法:python test_engine.py    # 全绿则护栏通过
"""
import sys
import numpy as np
import pandas as pd

from fib_engine import FibConfig, simulate, summarize_trades, limit_pct, Trade
import regime as rg

PASS, FAIL = 0, 0


def check(name, cond):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✓ {name}")
    else:
        FAIL += 1
        print(f"  ✗ {name}  <<< 失败")


def synth_ohlc(n=400, seed=7):
    """合成多段趋势的日线(确定性),足以触发金叉进出场。"""
    # 分段漂移:涨→跌→涨→盘整,制造均线交叉
    drift = np.concatenate([
        np.full(100, 0.010), np.full(80, -0.008),
        np.full(120, 0.012), np.full(n - 300, 0.000),
    ])
    rng = np.random.RandomState(seed)
    rets = drift + rng.normal(0, 0.012, n)
    close = 20 * np.cumprod(1 + rets)
    # 由 close 造合理的 OHLC
    high = close * (1 + np.abs(rng.normal(0, 0.006, n)))
    low = close * (1 - np.abs(rng.normal(0, 0.006, n)))
    openp = np.concatenate([[close[0]], close[:-1]]) * (1 + rng.normal(0, 0.003, n))
    idx = pd.bdate_range("2023-01-02", periods=n)
    return pd.DataFrame({"open": openp, "high": high, "low": low, "close": close,
                         "vol": rng.randint(1e6, 9e6, n)}, index=idx)


def test_t1_invariant():
    print("① T+1 不变量(开启 A 股规则)")
    df = synth_ohlc()
    trades = simulate(df, FibConfig(a_share_rules=True), "600000")
    check(f"产生了交易用于检验({len(trades)} 笔)", len(trades) > 0)
    same_day = [t for t in trades if t.entry_date == t.exit_date]
    check("无当日买当日卖", len(same_day) == 0)
    check("无 bars==0 的持仓", all(t.bars >= 1 for t in trades))


def test_no_future():
    print("② 无未来函数")
    df = synth_ohlc()
    cfg = FibConfig()
    trades = simulate(df, cfg, "600000")
    dates = list(df.index.strftime("%Y-%m-%d"))
    ok = True
    for t in trades:
        ei, xi = dates.index(t.entry_date), dates.index(t.exit_date)
        if xi < ei:          # 出场不能早于进场
            ok = False
    check("出场永不早于进场", ok)
    # 截断末尾不改变早期交易(早期信号不依赖未来数据)
    trades_full = simulate(df, cfg, "600000")
    trades_trunc = simulate(df.iloc[:300], cfg, "600000")
    early_full = [(t.entry_date, t.exit_date) for t in trades_full
                  if t.exit_date <= dates[290]]
    early_trunc = [(t.entry_date, t.exit_date) for t in trades_trunc
                   if t.exit_date <= dates[290]]
    check("截断未来数据不改变早期已平交易", early_full == early_trunc)


def test_limit_pct():
    print("③ 涨跌停幅度按板块")
    check("主板 600000 = 10%", abs(limit_pct("600000") - 0.10) < 1e-9)
    check("创业板 300750 = 20%", abs(limit_pct("300750") - 0.20) < 1e-9)
    check("科创板 688256 = 20%", abs(limit_pct("688256") - 0.20) < 1e-9)
    check("北交所 830799 = 30%", abs(limit_pct("830799") - 0.30) < 1e-9)


def test_regime_pit():
    print("④ regime 的 point-in-time(无前视)")
    # 合成指数
    rng = np.random.RandomState(3)
    n = 500
    close = pd.Series(4000 * np.cumprod(1 + (0.0005 + rng.normal(0, 0.01, n))),
                      index=pd.bdate_range("2022-01-03", periods=n))
    idx_df = pd.DataFrame({"close": close})
    full = rg.regime_series(idx_df)
    # 在第 400 根截断重算,前 350 根的敞口应完全一致(不依赖未来)
    trunc = rg.regime_series(idx_df.iloc[:400])
    common = full.index[:350]
    check("截断重算,历史敞口一致", bool((full.loc[common].values == trunc.loc[common].values).all()))
    check("敞口取值只在 {0,0.5,0.7,0.85,1.0} 等档位内",
          set(np.round(full.dropna().unique(), 3)).issubset({0.0, 0.5, 0.7, 0.85, 1.0}))


def test_summarize():
    print("⑤ 池化统计口径")
    def mk(ret):
        risk = 0.05
        return Trade(code="x", entry_date="2023-01-02", exit_date="2023-01-10",
                     entry=10, exit=10 * (1 + ret), stop0=9.5, bars=5,
                     ret=ret, ret_net=ret, r_multiple=ret / risk,
                     init_risk_pct=risk, mfe=max(ret, 0), mae=min(ret, 0),
                     exit_reason="ma_break")
    trades = [mk(0.20), mk(0.15), mk(-0.04), mk(-0.04), mk(-0.04)]  # 2 胜 3 负
    st = summarize_trades(trades)
    check("胜率 = 40%", st["win_rate"] == 40.0)
    check("期望R > 0(非对称为正)", st["expectancy_r"] > 0)
    check("profit factor = 赚/赔", abs(st["profit_factor"] - (0.35 / 0.12)) < 0.05)


def main():
    print("═" * 56)
    print("  量化引擎不变量测试")
    print("═" * 56)
    for t in (test_t1_invariant, test_no_future, test_limit_pct, test_regime_pit, test_summarize):
        t()
    print("─" * 56)
    print(f"  结果:{PASS} 通过 / {FAIL} 失败")
    print("═" * 56)
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
