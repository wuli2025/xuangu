# -*- coding: utf-8 -*-
"""
SENTIO 选股达人 · 多因子策略引擎
─────────────────────────────────────────────────────────────────────
在「情绪温度(collect.py)」之上，叠加价量技术因子，跑出可执行的交易策略：

  ① 取价：akshare 日线(前复权) ~2 年，逐股算技术因子
       动量(20/60/120日) · 趋势(MA多头排列+乖离) · RSI14 · ATR14 · 低波(20日波动)
  ② 复用情绪：读 collect.py 产出的 sentiment_latest.json 取 情绪温度 / 资金F
  ③ 横截面 z-score(winsorize ±3) → 复合「达人评分」(动量0.32/趋势0.20/资金0.18/低波0.10/情绪反向0.20)
       RSI>80 过热扣分；跌破MA60 趋势分自然走低
  ④ 组合构建：评分 Top-N → 每只 ATR 等风险仓位 + 欧奈尔7-8%/2×ATR 止损 + 3R 目标价
  ⑤ 回测：用同一动量逻辑做「月度再平衡」横截面回测，诚实给出
       CAGR / 月胜率 / 最大回撤 / 夏普，并对标等权基准。结果净于交易成本。

产出 strategy.json → output/ 与 polaris-app/public/sentio/（前端「建议策略」页直接渲染）。

合规与诚实声明：本引擎是「研究参考工具」，不是收益保证。任何「月化10%」之类的承诺都不可信——
策略给的是「提高胜率的纪律框架(选股+仓位+止损+止盈)」，市场有风险，回测不代表未来，盈亏自负。

依赖：akshare>=1.16, pandas>=2.2, numpy
用法：python strategy.py            # 跑 watchlist.json 全部
     python strategy.py 600519     # 只算指定代码(横截面会退化，建议跑全量)
"""
import os
import sys
import json
import time
import datetime as dt
from pathlib import Path

# 与 collect.py 同款：清代理 + Session 直连，避免本机 Clash 破坏到东财的 TLS。必须在 import akshare 前。
for _k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
    os.environ.pop(_k, None)
import requests as _rq
_orig_session_init = _rq.sessions.Session.__init__


def _no_proxy_session_init(self, *a, **k):
    _orig_session_init(self, *a, **k)
    self.trust_env = False
    self.proxies = {}


_rq.sessions.Session.__init__ = _no_proxy_session_init

import akshare as ak
import numpy as np
import pandas as pd

BASE = Path(__file__).resolve().parent
OUT_DIR = BASE / "output"
WATCHLIST = BASE / "watchlist.json"
FRONT_DIR = BASE.parent / "polaris-app" / "public" / "sentio"
SENTIMENT = OUT_DIR / "sentiment_latest.json"

# ── 复合评分权重（z-score 加权和）。动量主导、情绪反向制衡，符合零售可解释口径。──
WEIGHTS = {"动量": 0.32, "趋势": 0.20, "资金": 0.18, "低波": 0.10, "情绪反向": 0.20}

# ── 组合与风控参数 ──
TOP_N = 8          # 组合建议持仓数
MAX_PER_SECTOR = 3  # 单一板块最多入选数（强制行业分散，避免组合扎堆同一赛道）
RISK_PER_TRADE = 0.02   # 单笔风险预算 = 总资金 2%（R）
MAX_POS = 0.25     # 单只仓位上限 25%
INVEST_TARGET = 0.90    # 满仓目标（其余现金缓冲，过热时自动提高现金）
STOP_PCT = 0.08    # 欧奈尔硬止损 8% 上限
ATR_K = 2.0        # ATR 止损倍数
TARGET_R = 3.0     # 盈亏比 3:1

# ── 回测参数 ──
BT_MOM_MONTHS = 3      # 动量回看（月）≈ 60 交易日
BT_TOPK = 5            # 每期持有数
BT_COST = 0.003        # 换手部分的单边往返成本约 0.3%（佣金+印花税+滑点，诚实计提）
RF_ANNUAL = 0.015      # 无风险年利率（算夏普）

# ── 风险档位：动量回看 × 持仓数。进取=集中短周期(高收益高波动)，稳健=分散长周期 ──
MODES = [
    {"key": "稳健", "lookback": 6, "topk": 8, "desc": "分散持仓·长周期动量，波动小、回撤浅"},
    {"key": "均衡", "lookback": 3, "topk": 5, "desc": "默认档·收益与风险平衡"},
    {"key": "进取", "lookback": 2, "topk": 3, "desc": "集中龙头·短周期动量，冲高收益但回撤更深"},
]
TARGET_MONTHLY = float(os.environ.get("SENTIO_TARGET_MONTHLY", "0.10"))  # 目标月收益（默认10%）


def log(msg):
    print(f"[{dt.datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


# ───────────────────────── 取价 ─────────────────────────
# 不走东财 push2his(stock_zh_a_hist)：本机网络路径对东财高频/大响应会 TLS 重置(schannel
# server closed abruptly / RemoteDisconnect)，记忆里的「Clash+东财」老坑。改用新浪源
# stock_zh_a_daily —— 完全不同的 host，避开东财限流，前复权全历史一把取到。
def _sina_symbol(code):
    c = str(code)
    if c.startswith("6"):
        return "sh" + c
    if c.startswith(("4", "8")):
        return "bj" + c
    return "sz" + c


def fetch_hist(code, days=800):
    """前复权日线 DataFrame：index=日期(datetime)，列 close/high/low/vol。失败抛异常。"""
    end = dt.date.today()
    start = end - dt.timedelta(days=days)
    last_err = None
    for _ in range(3):
        try:
            df = ak.stock_zh_a_daily(
                symbol=_sina_symbol(code), adjust="qfq",
                start_date=start.strftime("%Y%m%d"), end_date=end.strftime("%Y%m%d"))
            if df is None or df.empty:
                raise ValueError("空数据")
            df = df.rename(columns={"volume": "vol"})
            df["date"] = pd.to_datetime(df["date"])
            df = df.set_index("date").sort_index()
            cols = [c for c in ["close", "high", "low", "vol"] if c in df.columns]
            return df[cols].apply(pd.to_numeric, errors="coerce")
        except Exception as e:
            last_err = e
            time.sleep(0.6)
    raise last_err


# ───────────────────────── 技术因子 ─────────────────────────
def rsi_wilder(close, n=14):
    d = close.diff()
    gain = d.clip(lower=0)
    loss = (-d).clip(lower=0)
    ag = gain.ewm(alpha=1 / n, adjust=False).mean()
    al = loss.ewm(alpha=1 / n, adjust=False).mean()
    rs = ag / al.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).iloc[-1]


def atr_wilder(df, n=14):
    h, l, c = df["high"], df["low"], df["close"]
    pc = c.shift(1)
    tr = pd.concat([(h - l), (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / n, adjust=False).mean()
    return float(atr.iloc[-1])


def pct_ret(close, n):
    if len(close) <= n:
        return np.nan
    return float(close.iloc[-1] / close.iloc[-1 - n] - 1)


def compute_factors(code, df):
    """从日线算一组最新因子。数据不足返回 None。"""
    c = df["close"].dropna()
    if len(c) < 70:
        return None
    ma20 = c.rolling(20).mean().iloc[-1]
    ma60 = c.rolling(60).mean().iloc[-1]
    ma120 = c.rolling(120).mean().iloc[-1] if len(c) >= 120 else c.rolling(min(len(c), 120)).mean().iloc[-1]
    last = float(c.iloc[-1])
    align = int(last > ma20) + int(ma20 > ma60) + int(ma60 > ma120)  # 0..3 多头排列
    dist60 = last / ma60 - 1 if ma60 else 0.0
    daily_ret = c.pct_change().dropna()
    vol20 = float(daily_ret.tail(20).std()) if len(daily_ret) >= 5 else np.nan
    try:
        atr = atr_wilder(df)
    except Exception:
        atr = last * 0.03
    try:
        rsi = float(rsi_wilder(c))
    except Exception:
        rsi = 50.0
    return {
        "code": code,
        "close": round(last, 3),
        "mom20": pct_ret(c, 20),
        "mom60": pct_ret(c, 60),
        "mom120": pct_ret(c, 120),
        "dist60": dist60,
        "align": align,
        "vol20": vol20,
        "atr": round(atr, 3),
        "atr_pct": round(atr / last, 4) if last else 0.04,
        "rsi": round(rsi, 1),
        "ma60": round(float(ma60), 3) if ma60 == ma60 else None,
    }


# ───────────────────────── 横截面 z-score 复合评分 ─────────────────────────
def zscore(series):
    s = pd.to_numeric(series, errors="coerce")
    mu, sd = s.mean(), s.std()
    if not sd or np.isnan(sd):
        return pd.Series(0.0, index=s.index)
    z = (s - mu) / sd
    return z.clip(-3, 3)


def pct_rank_0_100(series):
    s = pd.to_numeric(series, errors="coerce")
    r = s.rank(pct=True)
    return (r * 100).round(0)


def build_scores(rows, sentiment_map):
    """rows: list[factor dict] → DataFrame with 复合评分 + 子项分(0-100)。"""
    df = pd.DataFrame(rows).set_index("code")
    # 情绪温度 / 资金F 来自 collect 产出；缺失按中性
    df["temp"] = [sentiment_map.get(c, {}).get("temp", 50.0) for c in df.index]
    df["fundF"] = [sentiment_map.get(c, {}).get("fundF", 50.0) for c in df.index]

    # 原始因子合成
    df["mom_raw"] = 0.5 * df["mom60"].fillna(0) + 0.3 * df["mom120"].fillna(0) + 0.2 * df["mom20"].fillna(0)
    df["trend_raw"] = df["dist60"].fillna(0) + 0.05 * df["align"].fillna(0)
    df["fund_raw"] = df["fundF"].fillna(50)
    df["lowvol_raw"] = -df["vol20"].fillna(df["vol20"].median())
    df["contra_raw"] = -(df["temp"].fillna(50) - 50)  # 越冷越高（反向）

    # z-score
    z_mom = zscore(df["mom_raw"])
    z_trend = zscore(df["trend_raw"])
    z_fund = zscore(df["fund_raw"])
    z_lowvol = zscore(df["lowvol_raw"])
    z_contra = zscore(df["contra_raw"])

    composite = (WEIGHTS["动量"] * z_mom + WEIGHTS["趋势"] * z_trend
                 + WEIGHTS["资金"] * z_fund + WEIGHTS["低波"] * z_lowvol
                 + WEIGHTS["情绪反向"] * z_contra)
    # RSI 过热惩罚（>80 扣 0.8z；>90 扣 1.5z）
    penalty = pd.Series(0.0, index=df.index)
    penalty[df["rsi"] > 80] = -0.8
    penalty[df["rsi"] > 90] = -1.5
    composite = composite + penalty
    df["composite_z"] = composite
    df["达人评分"] = pct_rank_0_100(composite).fillna(50).astype(int)

    # 雷达子分（0-100 百分位，便于前端展示）
    df["分_动量"] = pct_rank_0_100(df["mom_raw"]).fillna(50).astype(int)
    df["分_趋势"] = pct_rank_0_100(df["trend_raw"]).fillna(50).astype(int)
    df["分_资金"] = pct_rank_0_100(df["fund_raw"]).fillna(50).astype(int)
    df["分_低波"] = pct_rank_0_100(df["lowvol_raw"]).fillna(50).astype(int)
    df["分_情绪"] = pct_rank_0_100(df["contra_raw"]).fillna(50).astype(int)
    return df.sort_values("composite_z", ascending=False)


# ───────────────────────── 交易计划（每只） ─────────────────────────
def trade_plan(row):
    entry = float(row["close"])
    atr = float(row["atr"])
    atr_stop = entry - ATR_K * atr
    pct_stop = entry * (1 - STOP_PCT)
    stop = max(atr_stop, pct_stop)          # 取较高者 → 把单笔最大亏损压在 8% 内
    risk_pct = (entry - stop) / entry if entry else STOP_PCT
    risk_pct = max(risk_pct, 0.005)
    target = entry + TARGET_R * (entry - stop)
    pos_pct = min(RISK_PER_TRADE / risk_pct, MAX_POS)   # 等风险仓位
    return {
        "entry": round(entry, 2),
        "stop": round(stop, 2),
        "stop_pct": round(-risk_pct * 100, 1),
        "target": round(target, 2),
        "target_pct": round((target / entry - 1) * 100, 1),
        "raw_pos": pos_pct,
        "atr_pct": round(float(row["atr_pct"]) * 100, 1),
        "rsi": float(row["rsi"]),
    }


def select_diversified(scored, sentiment_map):
    """按评分降序选 TOP_N，但每板块最多 MAX_PER_SECTOR 只 → 强制行业分散。"""
    chosen, sec_count = [], {}
    for c, r in scored.iterrows():
        sec = sentiment_map.get(c, {}).get("sector", "") or "其他"
        if sec_count.get(sec, 0) >= MAX_PER_SECTOR:
            continue
        chosen.append(c)
        sec_count[sec] = sec_count.get(sec, 0) + 1
        if len(chosen) >= TOP_N:
            break
    # 若分散约束太紧导致不足 TOP_N，用剩余高分补齐
    if len(chosen) < TOP_N:
        for c in scored.index:
            if c not in chosen:
                chosen.append(c)
            if len(chosen) >= TOP_N:
                break
    return scored.loc[chosen]


def build_picks(scored, sentiment_map):
    picks = []
    sel = select_diversified(scored, sentiment_map)
    plans = {c: trade_plan(r) for c, r in sel.iterrows()}
    raw_sum = sum(p["raw_pos"] for p in plans.values()) or 1.0
    # 归一到 INVEST_TARGET（其余现金）
    for c, r in sel.iterrows():
        p = plans[c]
        meta = sentiment_map.get(c, {})
        weight = round(p["raw_pos"] / raw_sum * INVEST_TARGET * 100, 1)
        picks.append({
            "code": c,
            "name": meta.get("name", c),
            "sector": meta.get("sector", ""),
            "score": int(r["达人评分"]),
            "radar": {
                "动量": int(r["分_动量"]), "趋势": int(r["分_趋势"]),
                "资金": int(r["分_资金"]), "低波": int(r["分_低波"]),
                "情绪": int(r["分_情绪"]),
            },
            "temp": round(float(r["temp"]), 1),
            "rsi": p["rsi"],
            "entry": p["entry"],
            "stop": p["stop"],
            "stop_pct": p["stop_pct"],
            "target": p["target"],
            "target_pct": p["target_pct"],
            "weight": weight,
            "reason": pick_reason(r),
        })
    return picks


def pick_reason(r):
    bits = []
    if r["分_动量"] >= 70:
        bits.append("动量强")
    if r["分_趋势"] >= 70:
        bits.append("多头排列")
    if r["分_资金"] >= 65:
        bits.append("主力净流入")
    if r["分_情绪"] >= 65:
        bits.append("情绪未过热")
    if r["分_低波"] >= 65:
        bits.append("波动可控")
    if r["rsi"] > 80:
        bits.append("⚠RSI过热")
    return " · ".join(bits) or "综合评分居前"


# ───────────────────────── 月度再平衡回测 ─────────────────────────
def _bt_series(m, fwd, mom_months, topk):
    """跑一组参数，返回 (strat_r[], bench_r[], dates[])。m=月末收盘宽表，fwd=下月收益。"""
    mom = m.pct_change(mom_months)
    strat_r, bench_r, dates = [], [], []
    prev = set()
    for i in range(mom_months, len(m) - 1):
        signal = mom.iloc[i].dropna()
        if len(signal) < 5:
            continue
        k = min(topk, max(1, len(signal) // 2))
        picks = list(signal.sort_values(ascending=False).head(k).index)
        fr = fwd.iloc[i][picks].dropna()
        if fr.empty:
            continue
        changed = len(set(picks) ^ prev) / (2 * k)
        strat_r.append(float(fr.mean()) - changed * BT_COST)
        bench_r.append(float(fwd.iloc[i].dropna().mean()))
        dates.append(m.index[i].strftime("%Y-%m"))
        prev = set(picks)
    return strat_r, bench_r, dates


def _cagr(r):
    if len(r) < 4:
        return None
    eq = np.cumprod(1 + np.array(r))
    return round(float(eq[-1] ** (12 / len(r)) - 1) * 100, 1)


def backtest(panel):
    """panel: dict code -> close Series(index=datetime)。
    主回测=月度横截面动量(BT_MOM_MONTHS/BT_TOPK)，外加多组参数稳健性矩阵，证明非过拟合单一配置。"""
    closes = pd.DataFrame({c: s for c, s in panel.items()}).sort_index()
    if closes.shape[1] < 5 or len(closes) < 120:
        return None
    m = closes.resample("ME").last().dropna(how="all")
    if len(m) < BT_MOM_MONTHS + 4:
        return None
    fwd = m.pct_change().shift(-1)
    strat_r, bench_r, dates = _bt_series(m, fwd, BT_MOM_MONTHS, BT_TOPK)
    if len(strat_r) < 4:
        return None
    out = summarize_bt(strat_r, bench_r, dates)
    # 稳健性矩阵：动量回看 {2,3,6} 月 × 持仓 {3,5,8}，看 CAGR 是否普遍跑赢基准
    sens = []
    for lb in (2, 3, 6):
        for tk in (3, 5, 8):
            sr, _, _ = _bt_series(m, fwd, lb, tk)
            cg = _cagr(sr)
            if cg is not None:
                sens.append({"lookback": lb, "topk": tk, "cagr": cg})
    out["sensitivity"] = sens
    return out


def _mode_stats(r, target):
    """一组月度收益 → 分布统计 + 达成目标概率。诚实呈现「冲高目标的代价」。"""
    a = np.array(r)
    n = len(a)
    eq = np.cumprod(1 + a)
    peak = np.maximum.accumulate(eq)
    mdd = float(((eq - peak) / peak).min())
    mean = float(a.mean())
    std = float(a.std(ddof=1)) if n > 1 else 0.0
    cagr = float(eq[-1] ** (12 / n) - 1) if n >= 4 else 0.0
    rf_m = RF_ANNUAL / 12
    sharpe = float((mean - rf_m) / std * np.sqrt(12)) if std > 0 else 0.0
    return {
        "months": n,
        "cagr": round(cagr * 100, 1),
        "monthly_mean": round(mean * 100, 2),
        "monthly_std": round(std * 100, 2),
        "win_rate": round(float((a > 0).mean()) * 100, 0),
        "max_drawdown": round(mdd * 100, 1),
        "sharpe": round(sharpe, 2),
        # 达成/反向击穿目标的历史频率（同一目标幅度）
        "p_hit": round(float((a >= target).mean()) * 100, 0),
        "p_lose": round(float((a <= -target).mean()) * 100, 0),
    }


BORROW_ANNUAL = 0.06   # 融资年利率（杠杆配置的资金成本，诚实计提）


def run_periodic(closes, freq, lookback, topk, leverage, ppy):
    """任意换仓频率 + 杠杆的横截面动量回测 → 返回「按月口径」的收益数组。
    freq: pandas resample 频率(ME/2W-FRI/W-FRI)；lookback: 回看「周期数」；ppy: 每年周期数。"""
    pf = closes.resample(freq).last().dropna(how="all")
    if len(pf) < lookback + 5:
        return None
    fwd = pf.pct_change().shift(-1)
    mom = pf.pct_change(lookback)
    borrow = BORROW_ANNUAL / ppy
    eq, rows, prev = 1.0, [], set()
    for i in range(lookback, len(pf) - 1):
        signal = mom.iloc[i].dropna()
        if len(signal) < 5:
            continue
        k = min(topk, max(1, len(signal) // 2))
        picks = list(signal.sort_values(ascending=False).head(k).index)
        fr = fwd.iloc[i][picks].dropna()
        if fr.empty:
            continue
        changed = len(set(picks) ^ prev) / (2 * k)
        r = float(fr.mean()) - changed * BT_COST
        r_lev = leverage * r - (leverage - 1) * borrow   # 杠杆放大收益，扣融资成本
        eq *= (1 + r_lev)
        rows.append((pf.index[i + 1], eq))
        prev = set(picks)
    if len(rows) < 6:
        return None
    s = pd.Series([e for _, e in rows], index=[d for d, _ in rows])
    meq = s.resample("ME").last().dropna()
    mret = meq.pct_change().dropna()
    return mret.to_numpy() if len(mret) >= 4 else None


def find_achiever(panel, target):
    """搜参数空间(换仓频率×回看×持仓数×杠杆)，找历史月均≥目标且回撤最浅的配置。
    诚实定位：这是「要够到月化目标，历史上得这么激进」，不是承诺。"""
    closes = pd.DataFrame({c: s for c, s in panel.items()}).sort_index()
    if closes.shape[1] < 5 or len(closes) < 120:
        return None
    grid = [("月度", "ME", 12, [2, 3]), ("双周", "2W-FRI", 26, [4, 6]), ("周度", "W-FRI", 52, [8, 12])]
    results = []
    for name, freq, ppy, lbs in grid:
        for lb in lbs:
            for tk in (1, 2, 3):
                for lev in (1.0, 1.5, 2.0):
                    mret = run_periodic(closes, freq, lb, tk, lev, ppy)
                    if mret is None:
                        continue
                    st = _mode_stats(list(mret), target)
                    st.update({"freq": name, "lookback": lb, "topk": tk, "leverage": lev})
                    results.append(st)
    if not results:
        return None
    tgt_pct = round(target * 100, 0)
    qual = [r for r in results if r["monthly_mean"] >= tgt_pct]
    if qual:
        best = min(qual, key=lambda r: abs(r["max_drawdown"]))  # 达标里回撤最浅
        best["achieved"] = True
    else:
        best = max(results, key=lambda r: r["monthly_mean"])     # 最接近目标
        best["achieved"] = False
    lev_txt = f"{best['leverage']:.1f}×杠杆" if best["leverage"] > 1 else "不加杠杆"
    best["config_text"] = f"{best['freq']}换仓 · 回看{best['lookback']}期 · 集中{best['topk']}只 · {lev_txt}"
    return best


def analyze_modes(panel, target):
    """对三档风险模式各跑回测 + 目标可行性。返回 (modes[], target_summary)。"""
    closes = pd.DataFrame({c: s for c, s in panel.items()}).sort_index()
    if closes.shape[1] < 5 or len(closes) < 120:
        return None, None
    m = closes.resample("ME").last().dropna(how="all")
    fwd = m.pct_change().shift(-1)
    modes = []
    for cfg in MODES:
        r, _, _ = _bt_series(m, fwd, cfg["lookback"], cfg["topk"])
        if len(r) < 4:
            continue
        st = _mode_stats(r, target)
        modes.append({**cfg, **st})
    if not modes:
        return None, None
    # 目标可行性：以「进取」档对标目标月收益，诚实给结论
    aggr = next((x for x in modes if x["key"] == "进取"), modes[-1])
    tgt_pct = round(target * 100, 0)
    feasible = aggr["monthly_mean"] >= tgt_pct
    verdict = (
        f"历史上「进取」档月均 {aggr['monthly_mean']}%，"
        + (f"达到了 {tgt_pct}% 目标" if feasible else f"低于 {tgt_pct}% 目标")
        + f"；但单月≥{tgt_pct}% 的频率仅 {aggr['p_hit']}%，"
        + f"单月≤-{tgt_pct}% 的频率 {aggr['p_lose']}%，最大回撤 {aggr['max_drawdown']}%。"
    )
    # 目标达成配置搜索：历史上「要够到月化目标得多激进」
    achiever = find_achiever(panel, target)
    if achiever:
        if achiever["achieved"]:
            verdict = (
                f"✅ 历史上确实有配置月均达到 {tgt_pct}%+：「{achiever['config_text']}」"
                f"月均 {achiever['monthly_mean']}%、年化 {achiever['cagr']}%——"
                f"但代价是最大回撤 {achiever['max_drawdown']}%、单月≤-{tgt_pct}% 的频率 {achiever['p_lose']}%。"
                f"高收益是用高风险换的，能拿住这套的人极少。"
            )
        else:
            verdict = (
                f"⚠ 即便搜遍 高频换仓+集中持仓+2×杠杆，历史最高也只到月均 {achiever['monthly_mean']}%"
                f"（{achiever['config_text']}），仍够不到稳定 {tgt_pct}%。"
                f"任何宣称稳定月化 {tgt_pct}% 的都是骗局。"
            )

    target_summary = {
        "target_monthly": tgt_pct,
        "best_mode": aggr["key"],
        "best_monthly_mean": aggr["monthly_mean"],
        "p_hit": aggr["p_hit"],
        "p_lose": aggr["p_lose"],
        "feasible": feasible,
        "verdict": verdict,
        "achiever": achiever,
        "honest_note": f"「月化{tgt_pct:.0f}%稳定收益」在A股不可持续——能冲高的月份必然伴随能巨亏的月份。"
                       "上面的『目标达成配置』是历史回测里硬凑到目标的最激进打法（高频/集中/杠杆），"
                       "回撤和爆仓风险同步放大，不是承诺、更不建议无脑照抄。理性做法：用纪律提高胜率、"
                       "止损控制单次亏损、把目标理解为『长期力争跑赢、单月不强求』。",
    }
    return modes, target_summary


def summarize_bt(strat_r, bench_r, dates):
    r = np.array(strat_r)
    b = np.array(bench_r)
    n = len(r)
    eq = np.cumprod(1 + r)
    eq_b = np.cumprod(1 + b)
    total = float(eq[-1] - 1)
    cagr = float(eq[-1] ** (12 / n) - 1)
    vol = float(r.std(ddof=1) * np.sqrt(12)) if n > 1 else 0.0
    rf_m = RF_ANNUAL / 12
    sharpe = float((r.mean() - rf_m) / r.std(ddof=1) * np.sqrt(12)) if n > 1 and r.std(ddof=1) > 0 else 0.0
    win = float((r > 0).mean())
    peak = np.maximum.accumulate(eq)
    mdd = float(((eq - peak) / peak).min())
    curve = [{"date": dates[i], "strat": round(float(eq[i]), 4), "bench": round(float(eq_b[i]), 4)}
             for i in range(n)]
    return {
        "months": n,
        "monthly_mean": round(float(r.mean()) * 100, 2),
        "monthly_std": round(float(r.std(ddof=1)) * 100, 2) if n > 1 else 0.0,
        "total_return": round(total * 100, 1),
        "cagr": round(cagr * 100, 1),
        "vol_ann": round(vol * 100, 1),
        "sharpe": round(sharpe, 2),
        "win_rate": round(win * 100, 0),
        "max_drawdown": round(mdd * 100, 1),
        "bench_total": round(float(eq_b[-1] - 1) * 100, 1),
        "curve": curve,
        "params": {"动量回看": f"{BT_MOM_MONTHS}月", "持仓数": BT_TOPK,
                   "再平衡": "月度", "成本计提": f"换手×{BT_COST*100:.1f}%"},
    }


# ───────────────────────── 市场态势 → 现金建议 ─────────────────────────
def cash_advice(board):
    temp = (board or {}).get("market_temp")
    lvl = (board or {}).get("market_level")
    cash = 1 - INVEST_TARGET
    note = "常规仓位"
    if temp is not None:
        if temp >= 80:
            cash, note = 0.40, "市场过热——大幅提高现金，只打高确定性"
        elif temp >= 65:
            cash, note = 0.25, "情绪偏热——收紧仓位、严格止损"
        elif temp <= 25:
            cash, note = 0.05, "情绪冰点——可逐步提高仓位左侧布局"
    return {"cash_pct": round(cash * 100, 0), "stance": note, "market_level": lvl, "market_temp": temp}


# ───────────────────────── 主流程 ─────────────────────────
def load_sentiment_map():
    """code -> {temp,fundF,name,sector}，来自 collect.py 产出。"""
    m = {}
    if SENTIMENT.exists():
        try:
            for r in json.loads(SENTIMENT.read_text(encoding="utf-8")):
                m[r["code"]] = {
                    "temp": r.get("temperature", 50.0),
                    "fundF": r.get("breakdown", {}).get("资金F", 50.0),
                    "name": r.get("name", r["code"]),
                    "sector": r.get("sector", ""),
                }
        except Exception as e:
            log(f"读 sentiment_latest 失败：{e}")
    return m


def write_json(paths, obj):
    for p in paths:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    wl = json.loads(WATCHLIST.read_text(encoding="utf-8"))["stocks"]
    args = [a for a in sys.argv[1:] if a.strip()]
    if args:
        wl = [s for s in wl if s["code"] in args] or [
            {"code": a, "name": a, "sector": "手动",
             "market": "sh" if a[0] == "6" else "sz"} for a in args]

    name_map = {s["code"]: s for s in wl}
    sentiment_map = load_sentiment_map()
    # 补全名称/板块（情绪缺失时用 watchlist）
    for s in wl:
        sentiment_map.setdefault(s["code"], {}).update({
            "name": s["name"], "sector": s.get("sector", ""),
            "temp": sentiment_map.get(s["code"], {}).get("temp", 50.0),
            "fundF": sentiment_map.get(s["code"], {}).get("fundF", 50.0),
        })

    today = dt.date.today().isoformat()
    log(f"策略宇宙 {len(wl)} 只 · 取价算因子…")
    rows, panel, failed = [], {}, []
    for i, s in enumerate(wl):
        code = s["code"]
        try:
            df = fetch_hist(code)
            panel[code] = df["close"].dropna()
            f = compute_factors(code, df)
            if f:
                rows.append(f)
                log(f"  [{i+1}/{len(wl)}] {code} {s['name']:<6} 动量60={f['mom60']:.1%} RSI={f['rsi']} ATR%={f['atr_pct']:.1%}")
            else:
                failed.append(code)
                log(f"  [{i+1}/{len(wl)}] {code} {s['name']} 数据不足，跳过")
        except Exception as e:
            failed.append(code)
            log(f"  [{i+1}/{len(wl)}] {code} {s['name']} 取价失败：{type(e).__name__} {str(e)[:40]}")
        time.sleep(0.35)

    if not rows:
        log("无可用因子数据，退出")
        return

    scored = build_scores(rows, sentiment_map)
    picks = build_picks(scored, sentiment_map)

    log("回测中（月度横截面动量）…")
    bt = backtest(panel)
    modes, target_summary = analyze_modes(panel, TARGET_MONTHLY)

    board = {}
    bpath = OUT_DIR / "board.json"
    if bpath.exists():
        try:
            board = json.loads(bpath.read_text(encoding="utf-8"))
        except Exception:
            pass
    cash = cash_advice(board)

    # 组合层预期（基于回测月度分布，诚实给区间，非承诺）
    expectation = None
    if bt:
        invested = INVEST_TARGET - cash["cash_pct"] / 100 + (1 - INVEST_TARGET)
        invested = max(0.3, min(1.0, INVEST_TARGET if cash["cash_pct"] <= 10 else 1 - cash["cash_pct"] / 100))
        base = bt["monthly_mean"] / 100
        std = bt["monthly_std"] / 100
        expectation = {
            "base_monthly": round(base * invested * 100, 1),
            "range_low": round((base - std) * invested * 100, 1),
            "range_high": round((base + std) * invested * 100, 1),
            "invested_pct": round(invested * 100, 0),
            "note": "区间=回测月均±1倍标准差×投入比例，是历史分布外推，不是收益保证。",
        }

    strategy = {
        "date": today,
        "universe": len(wl),
        "scored": len(rows),
        "failed": failed,
        "weights": WEIGHTS,
        "market": cash,
        "expectation": expectation,
        "modes": modes,
        "target": target_summary,
        "picks": picks,
        "ranked": [
            {"code": c, "name": sentiment_map.get(c, {}).get("name", c),
             "sector": sentiment_map.get(c, {}).get("sector", ""),
             "score": int(r["达人评分"]), "mom60": round(float(r["mom60"]) * 100, 1) if pd.notna(r["mom60"]) else None,
             "rsi": float(r["rsi"]), "temp": round(float(r["temp"]), 1)}
            for c, r in scored.iterrows()
        ],
        "backtest": bt,
        "disclaimer": "研究参考工具，非投资建议。回测净于成本但不代表未来；月化10%等承诺不可信。"
                      "本策略价值在于纪律(选股+仓位+止损+止盈)，股市有风险，盈亏自负。",
        "updated_at": dt.datetime.now().isoformat(timespec="seconds"),
    }
    write_json([OUT_DIR / "strategy.json", FRONT_DIR / "strategy.json"], strategy)
    log(f"策略完成 · Top{len(picks)} 已选 · 回测 {bt['cagr'] if bt else '—'}% CAGR / 胜率 {bt['win_rate'] if bt else '—'}% / 回撤 {bt['max_drawdown'] if bt else '—'}%")
    log(f"  → {OUT_DIR / 'strategy.json'}  &  {FRONT_DIR / 'strategy.json'}")


if __name__ == "__main__":
    main()
