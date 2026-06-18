# -*- coding: utf-8 -*-
"""
SENTIO · 斐波那契趋势跟踪引擎 (Fibonacci Trend-Following Engine)
═══════════════════════════════════════════════════════════════════════════════
把桌面《斐波那契趋势跟踪策略报告.html》的四大支柱，落成事件驱动、无未来函数的
逐股交易引擎：

  支柱一 · 进场   双均线金叉 EMA(n1)↑EMA(n2)，且收盘站上趋势均线 EMA(m)，ATR 过滤震荡
  支柱二 · 止损   斐波那契硬止损 = 入场价 − k×ATR(14)，k∈{1.0, 1.618, 2.618}（黄金比默认）
  支柱三 · 出场   均线移动止盈——收盘≥EMA(m) 一律持有(不主动止盈)，收盘<EMA(m) 才离场
  支柱四 · 仓位   分数凯利定基础仓位 + 斐波那契扩展位金字塔加码(可选)，单笔风险封顶

核心理念：损失有上限(斐波那契止损)、盈利无上限(均线之上一直拿) → 非对称收益。
胜率不重要，盈亏比(R 倍数)× 纪律才是 Alpha 来源。

两个函数对外：
  • simulate(df, cfg)      逐股事件驱动回测 → 交易明细 list[Trade]
  • signal_today(df, cfg)  评估最新一根已收盘 K → 当日信号(fresh_entry/holding/watch/none)

无外部状态、无 I/O，纯函数，便于回测与参数寻优。取价/落盘在 fib_scan.py。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, asdict
from typing import Optional

import numpy as np
import pandas as pd

# 斐波那契常数（止损系数候选 / 扩展位）
FIB_K = (1.0, 1.618, 2.618)            # 斐波那契止损指数候选
FIB_EXT = (1.0, 1.618, 2.618, 4.236)   # 金字塔加码触发的斐波那契扩展位
FIB_MA = (13, 21, 34, 55)              # 趋势均线候选（斐波那契数列）


# ───────────────────────── 参数 ─────────────────────────
@dataclass
class FibConfig:
    n1: int = 21          # 快线 EMA 周期（进场）
    n2: int = 55          # 慢线 EMA 周期（进场 / 趋势过滤）
    m: int = 34           # 趋势/移动止损均线 EMA 周期（出场）
    k: float = 1.618      # 斐波那契止损指数（×ATR）
    atr_n: int = 14       # ATR 周期
    atr_min_pct: float = 0.012   # ATR/价 下限：过滤无波动的震荡/僵尸股（避免来回扫损）
    atr_max_pct: float = 0.12    # ATR/价 上限：剔除妖股级别的极端波动
    entry_window: int = 3        # 金叉后多少根内仍算「新进场」有效窗口
    # 趋势闸：报告强调「只在单边趋势里进攻、回避震荡」——过滤逆势/弱势金叉
    require_slope: bool = True    # 进场要求慢线 EMA(n2) 向上 + 价站上慢线（真趋势）
    slope_lookback: int = 10      # 慢线斜率回看 K 数
    # 仓位 / 风控
    kelly_fraction: float = 0.5  # 分数凯利折扣（½ 凯利，控波动）
    risk_per_trade: float = 0.02 # 单笔风险预算 = 总资金 2%（按斐波那契止损距离定股数）
    max_pos: float = 0.30        # 单只仓位上限
    pyramid: bool = True         # 是否启用斐波那契金字塔加码
    pyramid_units: tuple = (4, 3, 2, 1)  # 各扩展位加仓单位（递减，底仓最重）
    # 成本
    cost_roundtrip: float = 0.002  # 单笔往返成本(佣金+印花+滑点)，A股诚实计提 ~0.2%
    # 回测起点
    warmup: int = 60             # 指标预热所需最少 K 线

    def label(self) -> str:
        return f"EMA{self.n1}/{self.n2}·趋势EMA{self.m}·斐波{self.k}×ATR"


@dataclass
class Trade:
    code: str
    entry_date: str
    exit_date: str
    entry: float
    exit: float
    stop0: float            # 初始斐波那契止损
    bars: int               # 持仓 K 线数
    ret: float              # 毛收益率(未计成本)
    ret_net: float          # 净收益率(计往返成本)
    r_multiple: float       # R 倍数 = 净收益 / 初始风险（非对称收益的核心度量）
    init_risk_pct: float    # 初始风险(入场到斐波那契止损的%)
    mfe: float              # 最大有利偏移(最高浮盈%)
    mae: float              # 最大不利偏移(最深浮亏%)
    exit_reason: str        # 'ma_break' 跌破均线 | 'fib_stop' 斐波那契硬止损 | 'eod' 数据末端

    def as_dict(self):
        return asdict(self)


# ───────────────────────── 指标 ─────────────────────────
def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()


def atr_wilder(df: pd.DataFrame, n: int = 14) -> pd.Series:
    h, l, c = df["high"], df["low"], df["close"]
    pc = c.shift(1)
    tr = pd.concat([(h - l), (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1.0 / n, adjust=False).mean()


def _indicators(df: pd.DataFrame, cfg: FibConfig) -> pd.DataFrame:
    """附加 ema_f / ema_s / ema_m / atr / golden(金叉布尔)。不改原 df。"""
    out = df.copy()
    c = out["close"]
    out["ema_f"] = ema(c, cfg.n1)
    out["ema_s"] = ema(c, cfg.n2)
    out["ema_m"] = ema(c, cfg.m)
    out["atr"] = atr_wilder(out, cfg.atr_n)
    cross = (out["ema_f"] > out["ema_s"]) & (out["ema_f"].shift(1) <= out["ema_s"].shift(1))
    out["golden"] = cross.fillna(False)
    out["atr_pct"] = out["atr"] / c
    out["ema_s_slope"] = out["ema_s"] - out["ema_s"].shift(cfg.slope_lookback)
    return out


def _trend_ok(cfg: FibConfig, close: float, ema_s: float, ema_s_slope: float) -> bool:
    """趋势闸：价站上慢线 + 慢线向上 = 真单边趋势（否则视为逆势/震荡金叉，跳过）。"""
    if not cfg.require_slope:
        return True
    if not (math.isfinite(ema_s) and math.isfinite(ema_s_slope)):
        return False
    return close > ema_s and ema_s_slope > 0


# ───────────────────────── 事件驱动单股回测 ─────────────────────────
def simulate(df: pd.DataFrame, cfg: FibConfig, code: str = "") -> list[Trade]:
    """
    无未来函数事件驱动回测：
      • 决策在第 i 根收盘，进场以 i+1 根开盘成交（无未来偷价）
      • 持仓期间：斐波那契硬止损盘中触发(low≤stop → 以 min(open,stop) 止损)
                 均线移动止损按收盘判定(close<EMA(m) → 该根收盘离场)，先触发者为准
    返回该股全部历史交易。
    """
    if df is None or len(df) < cfg.warmup + 5:
        return []
    d = _indicators(df, cfg)
    o = d["open"].to_numpy(dtype=float) if "open" in d else d["close"].to_numpy(dtype=float)
    c = d["close"].to_numpy(dtype=float)
    lo = d["low"].to_numpy(dtype=float)
    hi = d["high"].to_numpy(dtype=float)
    emaf = d["ema_f"].to_numpy(dtype=float)
    emas = d["ema_s"].to_numpy(dtype=float)
    emam = d["ema_m"].to_numpy(dtype=float)
    atr = d["atr"].to_numpy(dtype=float)
    atrp = d["atr_pct"].to_numpy(dtype=float)
    golden = d["golden"].to_numpy(dtype=bool)
    slope = d["ema_s_slope"].to_numpy(dtype=float)
    dates = [t.strftime("%Y-%m-%d") for t in d.index]
    n = len(d)

    trades: list[Trade] = []
    i = cfg.warmup
    while i < n - 1:
        # ── 进场判定（第 i 根收盘）──
        if (golden[i] and c[i] > emam[i] and cfg.atr_min_pct <= atrp[i] <= cfg.atr_max_pct
                and _trend_ok(cfg, c[i], emas[i], slope[i])):
            ei = i + 1                       # 次根开盘进场
            entry = o[ei]
            if not math.isfinite(entry) or entry <= 0:
                i += 1
                continue
            stop0 = entry - cfg.k * atr[i]   # 斐波那契硬止损
            if stop0 <= 0 or stop0 >= entry:
                i += 1
                continue
            init_risk = (entry - stop0) / entry
            peak = entry
            trough = entry
            exit_price = None
            exit_reason = "eod"
            xi = ei
            # ── 持仓管理：从进场根 ei 向后逐根 ──
            for j in range(ei, n):
                peak = max(peak, hi[j])
                trough = min(trough, lo[j])
                # 1) 斐波那契硬止损（盘中）——灾难保护，跌破即走
                if lo[j] <= stop0:
                    exit_price = min(o[j], stop0) if o[j] < stop0 else stop0
                    exit_reason = "fib_stop"
                    xi = j
                    break
                # 2) 均线移动止损（收盘）——站上 EMA(m) 一律持有，跌破才走
                if c[j] < emam[j] and j > ei:
                    exit_price = c[j]
                    exit_reason = "ma_break"
                    xi = j
                    break
            if exit_price is None:           # 数据末端仍持有，按最后收盘平
                exit_price = c[n - 1]
                xi = n - 1
                exit_reason = "eod"
            ret = exit_price / entry - 1
            ret_net = ret - cfg.cost_roundtrip
            r_mult = ret_net / init_risk if init_risk > 0 else 0.0
            trades.append(Trade(
                code=code, entry_date=dates[ei], exit_date=dates[xi],
                entry=round(entry, 3), exit=round(exit_price, 3), stop0=round(stop0, 3),
                bars=xi - ei, ret=round(ret, 4), ret_net=round(ret_net, 4),
                r_multiple=round(r_mult, 3), init_risk_pct=round(init_risk, 4),
                mfe=round(peak / entry - 1, 4), mae=round(trough / entry - 1, 4),
                exit_reason=exit_reason,
            ))
            i = xi + 1                       # 平仓后从下一根继续找信号（同一时间只持一仓）
        else:
            i += 1
    return trades


# ───────────────────────── 当日信号 ─────────────────────────
def signal_today(df: pd.DataFrame, cfg: FibConfig, code: str = "", name: str = "",
                 sector: str = "") -> Optional[dict]:
    """
    评估最新一根已收盘 K，给出当日可执行信号。
    state:
      fresh_entry  近 entry_window 根内金叉且仍满足进场条件 → 今日可建仓（首选）
      holding      更早已进场、价仍站上 EMA(m) 的有效持有/可加仓趋势中
      watch        快线逼近慢线(差<1.5%)，金叉在即
      none         无信号
    返回 dict（含入场价/斐波那契止损/趋势均线/建议仓位/理由），none 时返回 None。
    """
    if df is None or len(df) < cfg.warmup + 2:
        return None
    d = _indicators(df, cfg)
    last = len(d) - 1
    c = float(d["close"].iloc[last])
    emaf = float(d["ema_f"].iloc[last])
    emas = float(d["ema_s"].iloc[last])
    emam = float(d["ema_m"].iloc[last])
    atr = float(d["atr"].iloc[last])
    atrp = float(d["atr_pct"].iloc[last])
    if not all(math.isfinite(x) for x in (c, emaf, emas, emam, atr)) or c <= 0:
        return None

    # 近窗口内是否金叉
    gwin = bool(d["golden"].iloc[max(0, last - cfg.entry_window + 1): last + 1].any())
    slope = float(d["ema_s_slope"].iloc[last])
    above_m = c > emam
    above_s = c > emas
    atr_ok = cfg.atr_min_pct <= atrp <= cfg.atr_max_pct
    trend_ok = _trend_ok(cfg, c, emas, slope)
    gap_fs = (emaf - emas) / emas if emas else 0.0   # 快慢线间距(占慢线%)

    state, reason = "none", ""
    if gwin and above_m and atr_ok and trend_ok:
        state = "fresh_entry"
        bits = ["金叉确认", "站上趋势均线"]
        if above_s:
            bits.append("快线领先慢线")
        reason = " · ".join(bits)
    elif emaf > emas and above_m and atr_ok and trend_ok:
        # 趋势延续中：仍在均线之上 = 有效持有/趋势单
        dist_m = (c - emam) / emam
        state = "holding"
        reason = f"趋势延续 · 站上EMA{cfg.m} {dist_m*100:.1f}%（持有/回踩均线可加）"
    elif emaf <= emas and -0.015 <= gap_fs < 0 and above_m and atr_ok and slope > 0:
        state = "watch"
        reason = f"快线逼近慢线 {gap_fs*100:.1f}% · 金叉在即，盯盘待进"
    else:
        if not atr_ok:
            return None   # 震荡/僵尸，直接过滤掉，不进候选
        return None

    entry = c
    stop0 = entry - cfg.k * atr
    if stop0 <= 0:
        stop0 = entry * (1 - cfg.k * atrp)
    init_risk = (entry - stop0) / entry if entry else 0.08
    init_risk = max(init_risk, 0.005)
    # 分数凯利仓位（用通用经验值，individual 胜率/RR 在 fib_scan 用回测覆盖）
    pos = min(cfg.risk_per_trade / init_risk, cfg.max_pos)
    return {
        "code": code, "name": name or code, "sector": sector,
        "state": state, "reason": reason,
        "close": round(c, 3),
        "entry": round(entry, 3),
        "fib_stop": round(stop0, 3),
        "fib_stop_pct": round(-init_risk * 100, 1),
        "fib_k": cfg.k,
        "trail_ma": round(emam, 3),
        "trail_ma_label": f"EMA{cfg.m}",
        "dist_to_ma_pct": round((c - emam) / emam * 100, 1) if emam else 0.0,
        "atr_pct": round(atrp * 100, 2),
        "ema_gap_pct": round(gap_fs * 100, 2),
        "suggest_pos_pct": round(pos * 100, 1),
        "above_slow": above_s,
    }


# ───────────────────────── 交易明细 → 统计 ─────────────────────────
def summarize_trades(trades: list[Trade], hold_years: float = None) -> Optional[dict]:
    """池化交易统计：胜率/盈亏比/期望值(R)/profit factor/平均持仓 等。"""
    if not trades:
        return None
    r = np.array([t.ret_net for t in trades], dtype=float)
    rm = np.array([t.r_multiple for t in trades], dtype=float)
    wins = r[r > 0]
    losses = r[r <= 0]
    n = len(r)
    win_rate = len(wins) / n
    avg_win = float(wins.mean()) if len(wins) else 0.0
    avg_loss = float(losses.mean()) if len(losses) else 0.0
    payoff = (avg_win / abs(avg_loss)) if avg_loss < 0 else float("inf")
    gross_win = float(wins.sum())
    gross_loss = float(abs(losses.sum()))
    profit_factor = (gross_win / gross_loss) if gross_loss > 0 else float("inf")
    expectancy = float(r.mean())               # 每笔净期望收益
    expectancy_r = float(rm.mean())            # 每笔期望 R 倍数（非对称度量）
    # 凯利（用实测胜率与盈亏比）
    W, b = win_rate, (payoff if math.isfinite(payoff) else 5.0)
    kelly = W - (1 - W) / b if b > 0 else 0.0
    reasons = {}
    for t in trades:
        reasons[t.exit_reason] = reasons.get(t.exit_reason, 0) + 1
    return {
        "trades": n,
        "win_rate": round(win_rate * 100, 1),
        "avg_win_pct": round(avg_win * 100, 2),
        "avg_loss_pct": round(avg_loss * 100, 2),
        "payoff_ratio": round(payoff, 2) if math.isfinite(payoff) else None,
        "profit_factor": round(profit_factor, 2) if math.isfinite(profit_factor) else None,
        "expectancy_pct": round(expectancy * 100, 2),
        "expectancy_r": round(expectancy_r, 3),
        "avg_bars": round(float(np.mean([t.bars for t in trades])), 1),
        "max_win_pct": round(float(r.max()) * 100, 1),
        "max_loss_pct": round(float(r.min()) * 100, 1),
        "kelly_pct": round(max(kelly, 0.0) * 100, 1),
        "exit_reasons": reasons,
    }
