# -*- coding: utf-8 -*-
"""
SENTIO · 市场态势闸 (Market Regime Filter)
═══════════════════════════════════════════════════════════════════════════════
工业级量化系统的「择时底座」:用指数级趋势状态,给出 0/0.5/1 的仓位敞口乘子。
趋势跟踪策略最大的痛点是震荡/熊市里连续小亏——regime 闸的作用就是在烂市自动减仓
或停手,把月度收益分布右移、把回撤压浅(这是提升「月度一致性」最经典、性价比最高的手段)。

设计要点(全部 point-in-time,无未来函数):
  • 基准指数:沪深300(sh000300),代表大盘趋势;新浪源,避开东财 TLS 坑。
  • 三档敞口(趋势阶梯):
      1.0  牛 / 健康上行  —— 收盘>MA200 且 MA50>MA200 且 收盘>MA50(多头排列)
      0.5  震荡 / 回踩 / 修复 —— 多头排列被部分破坏(回踩 MA50,或熊末 MA50 转头向上)
      0.0  熊 / 破位      —— 收盘<MA200 且 MA50 走平/向下
  • 敞口在使用时滞后 1 个交易日(decision lag):某日的进场决策只能用「前一日收盘」算出的
    regime,杜绝用当日未来信息。对外用 asof 对齐到个股交易日。

对外接口:
  • fetch_index(symbol)        取指数日线(open/high/low/close)
  • regime_series(index_df)    → pd.Series(index=日期, value∈{0,0.5,1}),已滞后 1 日
  • exposure_asof(series, date)→ 某日可用的敞口(point-in-time 查表)
  • regime_today(index_df)     → dict(label/exposure/detail),供前端 & 当日信号展示

独立自检:python regime.py            # 拉指数,打印最新 regime + 近 10 日阶梯
"""
from __future__ import annotations

import os
import datetime as dt

# 清代理 + Session 直连(同 collect/strategy:本机 Clash 破坏新浪/东财 TLS)。必须在 import akshare 前。
for _k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
    os.environ.pop(_k, None)
import requests as _rq
_orig = _rq.sessions.Session.__init__


def _no_proxy(self, *a, **k):
    _orig(self, *a, **k)
    self.trust_env = False
    self.proxies = {}


_rq.sessions.Session.__init__ = _no_proxy

import numpy as np
import pandas as pd
import akshare as ak

# ── 参数 ──
INDEX_SYMBOL = "sh000300"   # 沪深300:覆盖面广、代表大盘趋势(可换 sh000905 中证500 / sz399006 创业板)
MA_FAST = 50
MA_SLOW = 200
SLOPE_LOOKBACK = 20         # MA50 斜率回看(判健康度)


def fetch_index(symbol: str = INDEX_SYMBOL, days: int = 1400) -> pd.DataFrame:
    """指数日线 DataFrame(index=日期, 列 open/high/low/close)。新浪源,失败抛异常。"""
    last_err = None
    for _ in range(3):
        try:
            df = ak.stock_zh_index_daily(symbol=symbol)
            if df is None or df.empty:
                raise ValueError("空数据")
            df["date"] = pd.to_datetime(df["date"])
            df = df.set_index("date").sort_index()
            cols = [c for c in ["open", "high", "low", "close"] if c in df.columns]
            df = df[cols].apply(pd.to_numeric, errors="coerce").dropna(subset=["close"])
            if days and len(df) > days:
                df = df.iloc[-days:]
            return df
        except Exception as e:
            last_err = e
    raise last_err


# 敞口映射(bear, neutral, bull)。A/B 实测:对「自下而上的个股趋势策略」,指数级闸门若把
# 震荡/破位一刀切到 0,会冗余地砍掉个股独立突破(CAGR 腰斩)。故默认改为「只在真熊市轻度减仓、
# 不停手」——bear=0.7 半档保护、neutral/bull=1.0 全额。详见 regime_ab.py 扫描结论。
LEVELS_DEFAULT = (0.7, 1.0, 1.0)
LEVELS_AGGRESSIVE = (0.0, 0.5, 1.0)   # 老的激进闸(适合自上而下/指数级策略,对本策略有害)


def _raw_regime(close: pd.Series, levels=LEVELS_DEFAULT) -> pd.Series:
    """逐日趋势阶梯(因果 rolling,每点只用历史)。levels=(熊,震荡,牛)敞口。未滞后。"""
    bear_e, neut_e, bull_e = levels
    ma_f = close.rolling(MA_FAST, min_periods=MA_FAST).mean()
    ma_s = close.rolling(MA_SLOW, min_periods=MA_SLOW).mean()
    ma_f_slope = ma_f - ma_f.shift(SLOPE_LOOKBACK)

    exp = pd.Series(np.nan, index=close.index)
    bull = (close > ma_s) & (ma_f > ma_s) & (close > ma_f)          # 多头排列健康上行
    bear = (close < ma_s) & (ma_f_slope <= 0)                       # 破位 + 快线走平/向下
    exp[bull] = bull_e
    exp[bear] = bear_e
    exp[exp.isna() & ma_s.notna()] = neut_e                         # 回踩多头/熊末修复=震荡档
    exp[ma_s.isna()] = 1.0                                          # MA200 预热期默认满仓
    return exp


def regime_series(index_df: pd.DataFrame, lag: int = 1, levels=LEVELS_DEFAULT) -> pd.Series:
    """对外:某日「可用」的敞口乘子。已滞后 lag 个交易日(decision lag,防未来函数)。"""
    exp = _raw_regime(index_df["close"], levels)
    return exp.shift(lag).ffill().fillna(1.0)


def exposure_asof(series: pd.Series, date) -> float:
    """point-in-time 查表:返回 <= date 的最近敞口。date 可为 str/Timestamp。"""
    ts = pd.Timestamp(date)
    s = series[series.index <= ts]
    if len(s) == 0:
        return 1.0
    return float(s.iloc[-1])


def _label(exp: float) -> str:
    if exp >= 0.95:
        return "进攻(健康上行)"
    if exp >= 0.6:
        return "中性偏多(轻度减仓)"
    if exp > 0.0:
        return "防守(震荡/回踩半仓)"
    return "停手(破位/熊市)"


def regime_today(index_df: pd.DataFrame) -> dict:
    """最新 regime 快照(供前端 & 当日信号)。用滞后后的可用敞口,口径与回测一致。"""
    close = index_df["close"]
    ma_f = close.rolling(MA_FAST, min_periods=MA_FAST).mean()
    ma_s = close.rolling(MA_SLOW, min_periods=MA_SLOW).mean()
    series = regime_series(index_df)
    exp = float(series.iloc[-1])
    last = float(close.iloc[-1])
    mf = float(ma_f.iloc[-1]) if pd.notna(ma_f.iloc[-1]) else None
    ms = float(ma_s.iloc[-1]) if pd.notna(ma_s.iloc[-1]) else None
    return {
        "symbol": INDEX_SYMBOL,
        "date": index_df.index[-1].strftime("%Y-%m-%d"),
        "close": round(last, 2),
        "ma_fast": round(mf, 2) if mf else None,
        "ma_slow": round(ms, 2) if ms else None,
        "exposure": exp,
        "label": _label(exp),
        "detail": (
            f"指数 {last:.0f} · MA{MA_FAST} {mf:.0f} · MA{MA_SLOW} {ms:.0f} → 建议敞口 {exp:.0%}"
            if mf and ms else f"建议敞口 {exp:.0%}(指标预热中)"
        ),
        "advice": {
            1.0: "趋势健康,正常按策略满额进场。",
            0.5: "震荡/回踩,新进场仓位减半、严格止损,优先持有已盈利单。",
            0.0: "大盘破位,停止新开仓,只留强势持仓,提高现金。",
        }.get(exp, "按策略执行"),
    }


if __name__ == "__main__":
    print("拉取沪深300指数(新浪源)…", flush=True)
    df = fetch_index()
    print(f"  {len(df)} 根 {df.index[0].date()} → {df.index[-1].date()}")
    today = regime_today(df)
    print("\n── 当前市场态势 ──")
    for k, v in today.items():
        print(f"  {k:10}: {v}")
    series = regime_series(df)
    print("\n── 近 12 个交易日敞口阶梯(已滞后1日) ──")
    for d, e in series.tail(12).items():
        print(f"  {d.date()}  {e:>4.1f}  {_label(e)}")
    # 历史敞口分布(看 regime 闸把多少时间判为防守/中性)
    vc = series.value_counts(normalize=True).sort_index()
    print("\n── 历史敞口时间占比 ──")
    for e, pct in vc.items():
        print(f"  {_label(e):16} {pct*100:5.1f}%")
