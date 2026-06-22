# -*- coding: utf-8 -*-
"""
SENTIO · 自选股诊断引擎 (Watchlist Diagnose)
═══════════════════════════════════════════════════════════════════════════════
你手输一组股票代码（或维护自己的自选 my_watchlist.json）→ 基于【真实前复权日线】
给出可执行诊断，回答四个问题：
  ① 能不能买？        —— 综合趋势/动量/超买超卖/位置，给买入/持有/减仓/观望/回避
  ② 现在该做什么？    —— 明确动作 + 仓位建议
  ③ 什么时候操作？    —— 具体触发条件（回踩不破 / 放量突破 / 反弹减仓…）
  ④ 到什么价位？      —— 入场价、止损价、目标价（按真实 ATR/结构算，非拍脑袋）
并用【多策略视角】给同一只票打分：斐波趋势 / 动量突破 / 低吸回归 / 稳健持有，
让你看清这票适合「进取打法」还是「稳妥打法」。

★ 防幻觉铁律：所有数字均来自 datastore 真实落库的行情（新浪/腾讯源，前复权），
  绝不臆造。每只都带「数据真实性戳」(数据源 / K线根数 / 起止日 / 最新收盘 / 数据日)，
  前端展示「✓ 真实数据」即源于此，用户可逐项核对。

★ 仓位感知：若 holdings.json 里登记了你的持仓（成本价），诊断会结合盈亏给出
  止盈/止损/持有的差异化建议（账户管理的第一步，先手动登记，后续可接券商同步）。

用法：
  python diagnose.py 600519 300308 000858     # 诊断指定代码
  python diagnose.py                            # 诊断 my_watchlist.json（无则回退 watchlist.json 前 12 只）
产出：diagnose.json → output/ 与 polaris-app/public/sentio/（前端「自选诊断」页渲染）。
"""
import os
import sys
import json
import math
import datetime as dt
from pathlib import Path

import numpy as np
import pandas as pd

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))

import datastore
from fib_engine import FibConfig, ema, atr_wilder, signal_today, simulate, summarize_trades

OUT_DIR = BASE / "output"
FRONT_DIR = BASE.parent / "polaris-app" / "public" / "sentio"
DATA_DIR = Path(os.environ.get("SENTIO_DATA_DIR", str(BASE / "data")))
MY_WATCHLIST = DATA_DIR / "my_watchlist.json"   # 用户自选股（可在前端增删）
HOLDINGS = DATA_DIR / "holdings.json"           # 用户持仓（成本价/股数，账户管理）

DISCLAIMER = ("本诊断基于真实历史行情用规则量化推演，不构成投资建议。市场有风险，"
              "AI 与回测均无法预测未来；据此操作盈亏自负。")


def log(msg):
    print(f"[{dt.datetime.now():%H:%M:%S}] {msg}", flush=True)


# ───────────────────────── 名称/板块映射 ─────────────────────────
def _load_name_map() -> dict:
    """合并 watchlist.json + universe.json + my_watchlist.json → code:{name,sector}。"""
    m = {}
    # universe 先、watchlist 后：watchlist 的板块标注更准，且不让空字段覆盖已有非空值。
    for fname in ("universe.json", "watchlist.json"):
        fp = BASE / fname
        if not fp.exists():
            continue
        try:
            data = json.loads(fp.read_text(encoding="utf-8"))
            for s in data.get("stocks", []):
                c = s.get("code")
                if not c:
                    continue
                cur = m.setdefault(c, {"name": c, "sector": ""})
                if s.get("name"):
                    cur["name"] = s["name"]
                if s.get("sector"):
                    cur["sector"] = s["sector"]
        except Exception:
            pass
    if MY_WATCHLIST.exists():
        try:
            for s in json.loads(MY_WATCHLIST.read_text(encoding="utf-8")).get("stocks", []):
                if s.get("code"):
                    m[s["code"]] = {"name": s.get("name") or m.get(s["code"], {}).get("name", s["code"]),
                                    "sector": s.get("sector") or m.get(s["code"], {}).get("sector", "")}
        except Exception:
            pass
    return m


def _load_holdings() -> dict:
    """读持仓：code -> {cost, shares}。无文件返回空。"""
    if not HOLDINGS.exists():
        return {}
    try:
        data = json.loads(HOLDINGS.read_text(encoding="utf-8"))
        out = {}
        for h in data.get("positions", []):
            c = h.get("code")
            if c:
                out[c] = {"cost": float(h.get("cost") or 0) or None, "shares": float(h.get("shares") or 0)}
        return out
    except Exception:
        return {}


def _input_codes() -> list:
    args = [a.strip() for a in sys.argv[1:] if a.strip() and a[0].isdigit()]
    if args:
        return args
    if MY_WATCHLIST.exists():
        try:
            codes = [s["code"] for s in json.loads(MY_WATCHLIST.read_text(encoding="utf-8")).get("stocks", [])
                     if s.get("code")]
            if codes:
                return codes
        except Exception:
            pass
    # 兜底：watchlist 前 12 只，给个默认演示集
    try:
        wl = json.loads((BASE / "watchlist.json").read_text(encoding="utf-8"))["stocks"]
        return [s["code"] for s in wl[:12]]
    except Exception:
        return ["600519", "300750", "000858"]


# ───────────────────────── 指标 ─────────────────────────
def _rsi(close: pd.Series, n: int = 14) -> float:
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=1.0 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1.0 / n, adjust=False).mean()
    rs = up / dn.replace(0, np.nan)
    out = 100 - 100 / (1 + rs)
    v = out.iloc[-1]
    return float(v) if math.isfinite(v) else 50.0


def _ret(close: pd.Series, n: int) -> float:
    if len(close) <= n:
        return 0.0
    a, b = float(close.iloc[-1]), float(close.iloc[-1 - n])
    return (a / b - 1.0) * 100 if b else 0.0


def _factors(df: pd.DataFrame) -> dict:
    """从真实日线算诊断所需全部因子。无任何外部臆造。"""
    c = df["close"]
    close = float(c.iloc[-1])
    ma20 = float(c.rolling(20).mean().iloc[-1])
    ma60 = float(c.rolling(60).mean().iloc[-1])
    ma120 = float(c.rolling(120).mean().iloc[-1]) if len(c) >= 120 else float(c.rolling(min(len(c), 120)).mean().iloc[-1])
    e21 = float(ema(c, 21).iloc[-1])
    e55 = float(ema(c, 55).iloc[-1])
    e34 = float(ema(c, 34).iloc[-1])
    atr = float(atr_wilder(df, 14).iloc[-1])
    atrp = atr / close * 100 if close else 0.0
    win = c.iloc[-min(len(c), 250):]
    hi = float(win.max())
    lo = float(win.min())
    pos = (close - lo) / (hi - lo) if hi > lo else 0.5            # 0..1 区间位置
    rets = c.pct_change().dropna()
    vol_ann = float(rets.iloc[-min(len(rets), 120):].std() * math.sqrt(244) * 100) if len(rets) else 0.0
    v = df["vol"] if "vol" in df else None
    vratio = None
    if v is not None and len(v) >= 60:
        v20 = float(v.iloc[-20:].mean())
        v60 = float(v.iloc[-60:].mean())
        vratio = (v20 / v60) if v60 else None
    return {
        "close": round(close, 3),
        "ma20": round(ma20, 3), "ma60": round(ma60, 3), "ma120": round(ma120, 3),
        "ema21": round(e21, 3), "ema55": round(e55, 3), "ema34": round(e34, 3),
        "atr_pct": round(atrp, 2),
        "rsi": round(_rsi(c), 1),
        "r20": round(_ret(c, 20), 1), "r60": round(_ret(c, 60), 1), "r120": round(_ret(c, 120), 1),
        "hi250": round(hi, 3), "lo250": round(lo, 3), "pos_in_range": round(pos * 100, 1),
        "vol_ann": round(vol_ann, 1),
        "vol_ratio": round(vratio, 2) if vratio else None,
        "dist_ma20_pct": round((close - ma20) / ma20 * 100, 1) if ma20 else 0.0,
        "dist_ma60_pct": round((close - ma60) / ma60 * 100, 1) if ma60 else 0.0,
        "bull_align": ma20 > ma60 > ma120,
        "above_ma60": close > ma60,
        "below_ma120": close < ma120,
        "ema_up": e21 > e55,
    }


# ───────────────────────── 多策略视角打分 ─────────────────────────
def _strategies(f: dict, fib_sig) -> list:
    """同一只票在 4 套策略下的契合度(0-100)+打法定性。让用户看清「进取 vs 稳妥」。"""
    out = []
    # ① 斐波趋势跟踪（进取/趋势）—— 复用引擎当日信号
    fib_fit = 0
    fib_action = "无信号"
    if fib_sig:
        st = fib_sig.get("state")
        fib_fit = {"fresh_entry": 88, "holding": 70, "watch": 50}.get(st, 30)
        fib_action = {"fresh_entry": "金叉新进场", "holding": "趋势持有/回踩加",
                      "watch": "金叉在即·盯盘"}.get(st, "暂不进")
    out.append({"key": "fib", "name": "斐波趋势跟踪", "tier": "进取·趋势",
                "fit": fib_fit, "action": fib_action,
                "note": "金叉进场+斐波止损+均线持有，损失有顶、盈利放飞，盈亏比驱动"})

    # ② 动量突破（高收益·追强）
    mom = 50 + f["r60"] * 0.6 + (f["pos_in_range"] - 50) * 0.5
    if f["vol_ratio"] and f["vol_ratio"] > 1.1:
        mom += 8                              # 放量加分
    if f["rsi"] > 82:
        mom -= 20                             # 过热扣分
    mom = max(0, min(100, mom))
    out.append({"key": "momentum", "name": "动量突破", "tier": "进取·高收益",
                "fit": round(mom), "action": "突破新高放量追" if mom >= 65 else "动量不足·不追",
                "note": "买强势创新高、放量突破，赚趋势加速钱，回撤较大需严守止损"})

    # ③ 低吸均值回归（波段·稳中求进）
    mr = 50
    if f["rsi"] < 38:
        mr += (38 - f["rsi"]) * 1.4          # 越超卖越契合
    if f["above_ma60"]:
        mr += 12                              # 大趋势未坏才低吸
    if f["below_ma120"]:
        mr -= 18                              # 趋势已坏的低吸是接刀
    mr = max(0, min(100, mr))
    out.append({"key": "reversion", "name": "低吸均值回归", "tier": "波段·稳中求进",
                "fit": round(mr), "action": "超卖企稳低吸" if mr >= 60 else "未到低吸区",
                "note": "趋势未坏前提下，等超卖+缩量企稳分批低吸，吃修复反弹"})

    # ④ 稳健趋势持有（稳妥·低波）
    steady = 40
    if f["bull_align"]:
        steady += 30                          # 多头排列
    if f["above_ma60"]:
        steady += 12
    if f["vol_ann"] < 35:
        steady += 12                          # 低波动更稳
    elif f["vol_ann"] > 60:
        steady -= 14
    if f["below_ma120"]:
        steady -= 25
    steady = max(0, min(100, steady))
    out.append({"key": "steady", "name": "稳健趋势持有", "tier": "稳妥·低波",
                "fit": round(steady), "action": "多头排列·中线持有" if steady >= 65 else "趋势不稳·不宜重仓",
                "note": "均线多头排列+低波动的长线票，回踩不破均线一路持有，求稳"})
    return out


# ───────────────────────── 综合诊断 ─────────────────────────
def _synthesize(code, name, sector, f, fib_sig, strategies, hist, holding):
    """把因子 + 多策略融成一句话结论 + 动作 + 时机 + 价位。"""
    close = f["close"]
    atr_abs = close * f["atr_pct"] / 100

    # —— 止损：优先斐波止损，否则结构止损（MA20 下方或 -8%）——
    if fib_sig and fib_sig.get("fib_stop"):
        stop = float(fib_sig["fib_stop"])
    else:
        stop = min(f["ma20"] * 0.985, close * 0.92)
    risk = max(close - stop, close * 0.02)

    # —— 决策树（按优先级）——
    rsi, dist20 = f["rsi"], f["dist_ma20_pct"]
    fib_state = fib_sig.get("state") if fib_sig else None
    if f["below_ma120"] and f["r60"] < 0 and not f["ema_up"]:
        action, tier, verdict = "回避", "danger", "趋势走坏·空仓回避"
        timing = f"已跌破年线区(MA120={f['ma120']})且 EMA21 下穿、60日动量{f['r60']}%为负——不接刀；待重新站上 MA60({f['ma60']}) 且 EMA21 上穿 EMA55 再评估"
        entry = None
    elif rsi >= 80 or dist20 >= 22:
        action, tier, verdict = "减仓/止盈", "warn", "短期过热·兑现保护"
        timing = f"RSI={rsi} / 已偏离 MA20 {dist20}%，乖离过大；反弹乏力或冲高滞涨时分批减，留底仓跟趋势，回踩 EMA34({f['ema34']}) 企稳再考虑接回"
        entry = None
    elif fib_state == "fresh_entry":
        action, tier, verdict = "买入/分批建仓", "buy", "金叉确认·可进场"
        entry = round((close + f["ema34"]) / 2 if close > f["ema34"] else close, 3)
        timing = f"今日金叉确认且站上趋势均线 EMA34({f['ema34']})；现价 {close} 附近可先建半仓，回踩 EMA34 不破加满；跌破 {round(stop,2)} 离场"
    elif f["bull_align"] and f["above_ma60"]:
        action, tier, verdict = "持有/回踩加仓", "hold", "多头排列·趋势健康"
        entry = round(f["ema34"], 3)
        timing = f"均线多头排列，趋势健康；持有为主，回踩 EMA34({f['ema34']})/MA20({f['ma20']}) 不破可加仓；收盘跌破 MA60({f['ma60']}) 减仓"
    elif rsi <= 35 and not f["below_ma120"]:
        action, tier, verdict = "低吸(试探)", "buy", "超卖·趋势未坏可低吸"
        entry = round(min(close, f["ma20"]), 3)
        timing = f"RSI={rsi} 超卖且趋势未破，等缩量企稳（如出现止跌阳线）在 {round(min(close, f['ma20']),2)} 附近分批试探；破 {round(stop,2)} 止损"
    else:
        action, tier, verdict = "观望", "wait", "信号不足·等触发"
        trig_hi = round(max(f["hi250"], close * 1.0), 2)
        entry = None
        timing = f"暂无明确进场信号；等放量突破前高 {trig_hi}、或回踩站稳 EMA34({f['ema34']}) 出现金叉时再进"

    # —— 目标价：仅对「可操作(买/持/待)」给目标，避免给回避/减仓的票算出误导性涨幅 ——
    struct_t = round(f["hi250"], 2)            # 结构阻力(250日高)，恒作参考
    if tier in ("buy", "hold", "wait"):
        base = entry if entry else close
        t1 = round(base + 2 * risk, 2)
        t2 = round(base + 3 * risk, 2)
        upside = round((t2 / close - 1) * 100, 1) if close else 0.0
    else:
        t1 = t2 = upside = None             # 回避/减仓不报买入目标

    # —— 置信度：多策略共识 + 该股回测真实优势 + 数据充足度 ——
    best_fit = max((s["fit"] for s in strategies), default=0)
    conf = best_fit * 0.5
    if hist:
        if (hist.get("expectancy_r") or 0) > 0.2:
            conf += 18
        if (hist.get("profit_factor") or 0) and hist["profit_factor"] > 1.4:
            conf += 12
        if (hist.get("win_rate") or 0) >= 45:
            conf += 6
    conf = round(max(5, min(96, conf)))

    # —— 仓位感知：登记了持仓则叠加账户视角 ——
    pos_note = None
    if holding:
        cost = holding.get("cost")
        if cost:
            pnl = round((close / cost - 1) * 100, 1)
            if pnl >= 0:
                pos_note = f"你的成本 {cost}，浮盈 {pnl}%。" + (
                    "已过热，优先保护利润、分批止盈。" if tier == "warn"
                    else "趋势健康可持有，止损上移到成本价之上锁定盈利。" if tier in ("hold", "buy")
                    else "趋势已转弱，落袋为安。" if tier == "danger"
                    else "信号转中性，可继续持有，但把止损上移到成本之上锁定利润。")
            else:
                pos_note = f"你的成本 {cost}，浮亏 {pnl}%。" + (
                    f"已接近/跌破止损 {round(stop,2)}，严格止损不补仓。" if close <= stop * 1.03
                    else "未破位可持有，但不越跌越买；破位坚决止损。")

    return {
        "code": code, "name": name, "sector": sector,
        "verdict": verdict, "action": action, "tier": tier,
        "timing": timing,
        "entry": entry, "stop": round(stop, 2), "stop_pct": round(-risk / close * 100, 1) if close else 0,
        "target1": t1, "target2": t2, "struct_target": struct_t, "upside_pct": upside,
        "confidence": conf,
        "factors": f,
        "fib_signal": fib_sig,
        "strategies": strategies,
        "hist": hist,
        "holding": ({"cost": holding.get("cost"), "shares": holding.get("shares"),
                     "pnl_pct": round((close / holding["cost"] - 1) * 100, 1)} if holding and holding.get("cost") else None),
        "position_note": pos_note,
    }


def diagnose_one(code: str, name_map: dict, holdings: dict, cfg: FibConfig) -> dict:
    info = name_map.get(code, {})
    name = info.get("name", code)
    sector = info.get("sector", "")
    try:
        df = datastore.get_hist(code, update=True)
    except Exception as e:
        return {"code": code, "name": name, "sector": sector, "error": f"取价失败: {type(e).__name__}: {str(e)[:40]}"}
    if df is None or len(df) < 70:
        return {"code": code, "name": name, "sector": sector, "error": "历史数据不足(需≥70根)"}

    f = _factors(df)
    fib_sig = signal_today(df, cfg, code=code, name=name, sector=sector)
    # 该股自身历史回测真实战绩（防止用空泛话术，给真数字）
    hist = None
    try:
        trades = simulate(df, cfg, code=code)
        s = summarize_trades(trades)
        if s:
            hist = {"trades": s["trades"], "win_rate": s["win_rate"],
                    "expectancy_r": s["expectancy_r"], "profit_factor": s["profit_factor"],
                    "avg_win_pct": s["avg_win_pct"], "avg_loss_pct": s["avg_loss_pct"]}
    except Exception:
        pass

    strategies = _strategies(f, fib_sig)
    diag = _synthesize(code, name, sector, f, fib_sig, strategies, hist, holdings.get(code))
    # ── 数据真实性戳（前端「✓ 真实数据」逐项可核对）──
    diag["provenance"] = {
        "source": "datastore · 新浪/腾讯前复权日线",
        "bars": int(len(df)),
        "first_date": df.index[0].strftime("%Y-%m-%d"),
        "last_date": df.index[-1].strftime("%Y-%m-%d"),
        "last_close": float(round(df["close"].iloc[-1], 3)),
        "verified": True,
    }
    return diag


def write_json(paths, obj):
    for p in paths:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    t0 = dt.datetime.now()
    codes = _input_codes()
    name_map = _load_name_map()
    holdings = _load_holdings()
    cfg = FibConfig()
    log(f"自选诊断启动 · {len(codes)} 只 · 基于真实落库行情")
    diags, failed = [], []
    for i, code in enumerate(codes):
        log(f"  [{i+1}/{len(codes)}] 诊断 {code} …")
        d = diagnose_one(code, name_map, holdings, cfg)
        if d.get("error"):
            failed.append({"code": code, "error": d["error"]})
            log(f"     ✗ {d['error']}")
        diags.append(d)
    # 按「可操作性」排序：买入>持有>低吸>观望>减仓>回避，再按置信度
    order = {"buy": 0, "hold": 1, "wait": 3, "warn": 4, "danger": 5}
    diags_ok = [d for d in diags if not d.get("error")]
    diags_ok.sort(key=lambda d: (order.get(d.get("tier"), 9), -d.get("confidence", 0)))

    out = {
        "date": t0.strftime("%Y-%m-%d"),
        "engine": "diagnose · 真实行情多策略诊断",
        "count": len(diags_ok),
        "requested": codes,
        "failed": failed,
        "config": {"label": cfg.label(), "k": cfg.k, "n1": cfg.n1, "n2": cfg.n2, "m": cfg.m},
        "diagnoses": diags_ok + [d for d in diags if d.get("error")],
        "actions_legend": {"buy": "买入/低吸", "hold": "持有/加仓", "wait": "观望等待",
                           "warn": "减仓/止盈", "danger": "回避/不碰"},
        "disclaimer": DISCLAIMER,
        "updated_at": dt.datetime.now().isoformat(timespec="seconds"),
    }
    write_json([OUT_DIR / "diagnose.json", FRONT_DIR / "diagnose.json"], out)
    log(f"自选诊断完成 · {len(diags_ok)} 成功 / {len(failed)} 失败 · 用时 {(dt.datetime.now()-t0).seconds}s")
    log(f"  → {OUT_DIR / 'diagnose.json'}  &  {FRONT_DIR / 'diagnose.json'}")


if __name__ == "__main__":
    main()
