# -*- coding: utf-8 -*-
"""
SENTIO · 斐波那契趋势跟踪 — 扫描 + 回测编排器
═══════════════════════════════════════════════════════════════════════════════
data flow：
  ① 取价   新浪日线(前复权)~3年，逐股；本地磁盘缓存(当日)，让参数寻优不反复打网络
  ② 回测   逐股 simulate → 池化交易统计(胜率/盈亏比/期望R/profit factor)
           + 组合层日频权益曲线(固定分数风险·最多N并发·复利) 对标等权买入持有
  ③ 寻优   网格扫 斐波系数k × 趋势均线m × 趋势闸 → 证明「edge 跨参数普遍为正=非过拟合」
           并选出运行配置
  ④ 选股   用最优配置跑 signal_today，今日候选(fresh_entry/holding/watch)排序 + 个股历史战绩
  ⑤ 产出   fib_strategy.json → output/ 与 polaris-app/public/sentio/（前端「斐波选股」页渲染）

诚实声明：研究参考工具，非投资建议。趋势策略在震荡市必然连续小亏，靠少数大趋势的非对称
盈利覆盖——回测有效≠未来有效，宇宙为龙头精选存在事后选择偏差，务必看「相对基准超额+回撤」。

用法：
  python fib_scan.py            # 全宇宙：回测+寻优+今日选股
  python fib_scan.py --quick    # 跳过参数寻优(只用默认配置)，更快
  python fib_scan.py 600519     # 指定代码
"""
import os
import sys
import json
import time
import pickle
import datetime as dt
from pathlib import Path

# 清代理 + Session 直连（记忆：Clash 破坏东财/新浪 TLS）。必须在 import akshare 前。
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

from fib_engine import (
    FibConfig, FIB_K, simulate, signal_today, summarize_trades,
)
import regime as rg

BASE = Path(__file__).resolve().parent
OUT_DIR = BASE / "output"
CACHE_DIR = BASE / "data" / "cache"
# 默认跑精选 watchlist;SENTIO_WATCHLIST=universe.json 可切到 build_universe.py 产出的大宇宙(P2-A)。
WATCHLIST = BASE / os.environ.get("SENTIO_WATCHLIST", "watchlist.json")
FRONT_DIR = BASE.parent / "polaris-app" / "public" / "sentio"
SENTIMENT = OUT_DIR / "sentiment_latest.json"

FETCH_DAYS = 1100      # ~3年日线
MAX_CONCURRENT = 6     # 组合层最多并发持仓
RF_ANNUAL = 0.015


def log(msg):
    print(f"[{dt.datetime.now():%H:%M:%S}] {msg}", flush=True)


# ───────────────────────── 取价（带当日磁盘缓存） ─────────────────────────
def _sina_symbol(code):
    c = str(code)
    if c.startswith("6"):
        return "sh" + c
    if c.startswith(("4", "8")):
        return "bj" + c
    return "sz" + c


def fetch_hist(code, days=FETCH_DAYS, use_cache=True):
    """前复权日线 DataFrame(open/high/low/close/vol)。当日缓存命中则秒回。失败抛异常。"""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    today = dt.date.today().isoformat()
    cf = CACHE_DIR / f"{code}_{today}.pkl"
    if use_cache and cf.exists():
        try:
            return pickle.loads(cf.read_bytes())
        except Exception:
            pass
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
            cols = [c for c in ["open", "high", "low", "close", "vol"] if c in df.columns]
            df = df[cols].apply(pd.to_numeric, errors="coerce").dropna(subset=["close"])
            if use_cache:
                cf.write_bytes(pickle.dumps(df))
                # 清掉同代码的旧日期缓存
                for old in CACHE_DIR.glob(f"{code}_*.pkl"):
                    if old.name != cf.name:
                        try:
                            old.unlink()
                        except Exception:
                            pass
            return df
        except Exception as e:
            last_err = e
            time.sleep(0.6)
    raise last_err


# ───────────────────────── 组合层日频回测 ─────────────────────────
def portfolio_backtest(dfs: dict, cfg: FibConfig, max_concurrent=MAX_CONCURRENT, regime_exp=None, trades=None):
    """
    用各股 simulate 出的交易(精确进/出场日与净收益)，跑组合层日频权益曲线：
      固定分数风险(min(risk/init_risk, max_pos)×凯利折扣) · 最多 N 并发 · 出场结算复利。
    对标：等权买入持有(同窗口)。返回 metrics + 月度曲线(strat/bench)。

    regime_exp: 可选的市场态势敞口序列(regime.regime_series 产出，已滞后1日，point-in-time)。
      进场日按 exposure_asof(进场日) 缩放仓位：0=跳过该进场，0.5=半仓，1=满仓。None=不启用(旧行为)。
    trades: 可选的预算交易列表(walk-forward OOS 用——按窗口选参拼出的样本外交易)。
      给定则跳过内部 simulate，直接用这批交易跑组合层权益，复用同一套基准/指标口径。
    """
    if trades is not None:
        all_trades = list(trades)
    else:
        all_trades = []
        for code, df in dfs.items():
            for t in simulate(df, cfg, code):
                all_trades.append(t)
    if len(all_trades) < 8:
        return None, all_trades

    # 统一交易日历（所有股票收盘日并集，限定回测窗口）
    idx = sorted(set().union(*[set(df.index) for df in dfs.values()]))
    idx = pd.DatetimeIndex(idx)
    # 等权基准 NAV（每日等权平均的个股日收益累乘）
    rets = []
    for code, df in dfs.items():
        r = df["close"].reindex(idx).ffill().pct_change(fill_method=None)
        rets.append(r)
    bench_daily = pd.concat(rets, axis=1).mean(axis=1).fillna(0.0)
    bench_nav = (1 + bench_daily).cumprod()

    # 事件：进场/出场。按日推进，维护 equity 与 在场仓位
    entries = {}
    exits = {}
    for k, t in enumerate(all_trades):
        entries.setdefault(pd.Timestamp(t.entry_date), []).append(k)
        exits.setdefault(pd.Timestamp(t.exit_date), []).append(k)

    equity = 1.0
    open_pos = {}     # trade_idx -> capital_alloc(进场时占用的权益额)
    nav = pd.Series(index=idx, dtype=float)
    realized_curve = []
    for d in idx:
        # 先结算今日离场（出场价已含成本，净收益 ret_net）
        for k in exits.get(d, []):
            if k in open_pos:
                alloc = open_pos.pop(k)
                equity += alloc * all_trades[k].r_multiple * all_trades[k].init_risk_pct  # = alloc*ret_net
        # 再处理今日进场（有空位才开）
        for k in entries.get(d, []):
            if len(open_pos) >= max_concurrent:
                continue
            # 市场态势闸：风险关停跳过新开仓，半仓档位仓位减半(point-in-time)
            exp = rg.exposure_asof(regime_exp, d) if regime_exp is not None else 1.0
            if exp <= 0:
                continue
            t = all_trades[k]
            pos_frac = min(cfg.risk_per_trade / max(t.init_risk_pct, 0.005), cfg.max_pos) * cfg.kelly_fraction * exp
            open_pos[k] = equity * pos_frac
        nav[d] = equity
    nav = nav.ffill()

    # 用月度采样画曲线 + 日频指标
    mser = nav.resample("ME").last().dropna()
    mbench = bench_nav.reindex(nav.index).ffill().resample("ME").last().dropna()
    common = mser.index.intersection(mbench.index)
    mser, mbench = mser[common], mbench[common]
    if len(mser) < 4:
        return None, all_trades
    daily_ret = nav.pct_change(fill_method=None).dropna()
    n_days = len(daily_ret)
    years = max(n_days / 244.0, 0.3)
    cagr = float(nav.iloc[-1] ** (1 / years) - 1)
    peak = nav.cummax()
    mdd = float(((nav - peak) / peak).min())
    vol = float(daily_ret.std() * np.sqrt(244))
    sharpe = float((daily_ret.mean() * 244 - RF_ANNUAL) / vol) if vol > 0 else 0.0
    bench_cagr = float(bench_nav.iloc[-1] ** (1 / years) - 1)
    bpeak = bench_nav.cummax()
    bmdd = float(((bench_nav - bpeak) / bpeak).min())

    curve = [{"date": d.strftime("%Y-%m"),
              "strat": round(float(mser.loc[d] / mser.iloc[0]), 4),
              "bench": round(float(mbench.loc[d] / mbench.iloc[0]), 4)}
             for d in common]
    metrics = {
        "start": idx[0].strftime("%Y-%m-%d"),
        "end": idx[-1].strftime("%Y-%m-%d"),
        "years": round(years, 1),
        "total_return": round(float(nav.iloc[-1] - 1) * 100, 1),
        "cagr": round(cagr * 100, 1),
        "max_drawdown": round(mdd * 100, 1),
        "vol_ann": round(vol * 100, 1),
        "sharpe": round(sharpe, 2),
        "bench_total": round(float(bench_nav.iloc[-1] - 1) * 100, 1),
        "bench_cagr": round(bench_cagr * 100, 1),
        "bench_mdd": round(bmdd * 100, 1),
        "excess": round(float(nav.iloc[-1] - bench_nav.iloc[-1]) * 100, 1),
        "max_concurrent": max_concurrent,
        "curve": curve,
    }
    return metrics, all_trades


# ───────────────────────── 参数寻优（证明非过拟合） ─────────────────────────
def grid_search(dfs: dict):
    """扫 斐波系数k × 趋势均线m × 趋势闸 → 每组池化期望R/profit factor/胜率/交易数。
    选优：先按 profit_factor 取若干强 edge 候选，再用组合层夏普(风险调整收益)定选——
    避免只盯绝对期望R 而忽略波动。返回 (matrix[], best_cfg, best_stat, slope_compare)。
    普遍正期望 = edge 稳健非过拟合。"""
    matrix = []
    cand = []
    for k in FIB_K:
        for m in (21, 34, 55):
            cfg = FibConfig(k=k, m=m, require_slope=True)
            trades = []
            for code, df in dfs.items():
                trades.extend(simulate(df, cfg, code))
            st = summarize_trades(trades)
            if not st:
                continue
            matrix.append({"k": k, "m": m, "trades": st["trades"],
                           "win_rate": st["win_rate"], "payoff": st["payoff_ratio"],
                           "profit_factor": st["profit_factor"], "expectancy_r": st["expectancy_r"]})
            if st["trades"] >= 20 and st["expectancy_r"] > 0:
                cand.append((cfg, st))
    # 取 profit_factor 前 4 的候选，用组合层夏普定选（风险调整后的最优运行配置）
    cand.sort(key=lambda x: -(x[1]["profit_factor"] or 0))
    best = None
    for cfg, st in cand[:4]:
        metrics, _ = portfolio_backtest(dfs, cfg)
        sharpe = metrics["sharpe"] if metrics else -9
        if best is None or sharpe > best[0]:
            best = (sharpe, cfg, st)

    # 趋势闸 on/off 对照（证明趋势过滤的价值）
    slope_cmp = []
    for use in (True, False):
        cfg = FibConfig(require_slope=use)
        trades = []
        for code, df in dfs.items():
            trades.extend(simulate(df, cfg, code))
        st = summarize_trades(trades)
        if st:
            slope_cmp.append({"require_slope": use, **{kk: st[kk] for kk in
                              ("trades", "win_rate", "profit_factor", "expectancy_r")}})
    best_cfg = best[1] if best else FibConfig()
    return matrix, best_cfg, best[2] if best else None, slope_cmp


# ───────────────────────── 情绪/名称映射 ─────────────────────────
def load_meta(wl):
    m = {s["code"]: {"name": s["name"], "sector": s.get("sector", "")} for s in wl}
    if SENTIMENT.exists():
        try:
            for r in json.loads(SENTIMENT.read_text(encoding="utf-8")):
                m.setdefault(r["code"], {})
                m[r["code"]]["temp"] = r.get("temperature")
                m[r["code"]].setdefault("name", r.get("name", r["code"]))
                m[r["code"]].setdefault("sector", r.get("sector", ""))
        except Exception:
            pass
    return m


def write_json(paths, obj):
    for p in paths:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


# ───────────────────────── 主流程 ─────────────────────────
def main():
    args = [a for a in sys.argv[1:] if a.strip()]
    quick = "--quick" in args
    codes = [a for a in args if not a.startswith("--")]

    wl = json.loads(WATCHLIST.read_text(encoding="utf-8"))["stocks"]
    if codes:
        wl = [s for s in wl if s["code"] in codes] or [
            {"code": c, "name": c, "sector": "手动"} for c in codes]
    meta = load_meta(wl)

    log(f"斐波那契趋势引擎 · 宇宙 {len(wl)} 只 · 取价(新浪日线~3年)…")
    dfs = {}
    failed = []
    for i, s in enumerate(wl):
        code = s["code"]
        try:
            df = fetch_hist(code)
            if len(df) >= 80:
                dfs[code] = df
                log(f"  [{i+1}/{len(wl)}] {code} {s['name']:<6} {len(df)} 根 "
                    f"{df.index[0].date()}→{df.index[-1].date()}")
            else:
                failed.append(code)
        except Exception as e:
            failed.append(code)
            log(f"  [{i+1}/{len(wl)}] {code} {s['name']} 取价失败 {type(e).__name__} {str(e)[:36]}")
        time.sleep(0.15)

    if len(dfs) < 5:
        log("可用数据不足 5 只，退出")
        return

    # ② 参数寻优 → 选运行配置
    if quick:
        cfg = FibConfig()
        matrix, slope_cmp, best_st = [], [], None
        log("（--quick）跳过寻优，用默认配置")
    else:
        log("参数寻优中（斐波系数 × 趋势均线 × 趋势闸）…")
        matrix, cfg, best_st, slope_cmp = grid_search(dfs)
        log(f"  → 最优运行配置：{cfg.label()}")

    # 市场态势(regime):始终算快照供前端/实盘风控;闸门默认关(A/B 实测对龙头宇宙不提升收益,
    # 仅作可选防御层,见 INDUSTRIAL_PLAN P1-A)。SENTIO_REGIME=1 启用最温和档 0.7/1/1。
    regime_snapshot, regime_exp = None, None
    use_regime_gate = os.environ.get("SENTIO_REGIME", "") in ("1", "true", "on")
    try:
        idx_df = rg.fetch_index()
        regime_snapshot = rg.regime_today(idx_df)
        log(f"市场态势:{regime_snapshot['label']} · 建议敞口 {regime_snapshot['exposure']:.0%}")
        if use_regime_gate:
            regime_exp = rg.regime_series(idx_df, levels=rg.LEVELS_DEFAULT)
            log("  regime 防御闸:已启用(熊市七成档 0.7/1/1)")
    except Exception as e:
        log(f"市场态势获取失败(不影响选股):{type(e).__name__}: {str(e)[:40]}")

    # ③ 组合层回测（用运行配置）
    log("组合层日频回测 + 池化交易统计…")
    metrics, all_trades = portfolio_backtest(dfs, cfg, regime_exp=regime_exp)
    pooled = summarize_trades(all_trades)

    # ③b Walk-forward 样本外验证（诚实化:样本内业绩是乐观上界，OOS 才是可信预期）。
    #    始终计算(便宜~2s 且是前端「IS vs OOS」诚实面板的数据源，与 --quick 解耦保证调度也有 OOS)。
    oos = None
    try:
        import walkforward as wf
        log("Walk-forward 样本外验证(train12/test6月滚动)…")
        oos = wf.run_oos(dfs)
        if oos and oos.get("verdict"):
            log(f"  OOS：{oos['verdict']['headline']}")
    except Exception as e:
        log(f"  walk-forward 异常(跳过):{type(e).__name__}: {str(e)[:50]}")

    # 个股历史战绩（供候选卡片展示「这只票历史上这套信号的表现」）
    per_stock = {}
    for code, df in dfs.items():
        st = summarize_trades(simulate(df, cfg, code))
        if st:
            per_stock[code] = {"trades": st["trades"], "win_rate": st["win_rate"],
                               "expectancy_r": st["expectancy_r"],
                               "profit_factor": st["profit_factor"]}

    # ④ 今日选股
    log("扫描今日信号…")
    cands = []
    for code, df in dfs.items():
        sig = signal_today(df, cfg, code, meta.get(code, {}).get("name", code),
                           meta.get(code, {}).get("sector", ""))
        if sig:
            sig["temp"] = meta.get(code, {}).get("temp")
            sig["hist"] = per_stock.get(code)
            cands.append(sig)
    # 排序：fresh_entry > holding > watch；同状态按个股历史期望R降序
    order = {"fresh_entry": 0, "holding": 1, "watch": 2}
    cands.sort(key=lambda x: (order.get(x["state"], 9),
                              -((x.get("hist") or {}).get("expectancy_r") or -9)))
    fresh = [c for c in cands if c["state"] == "fresh_entry"]

    # 有效性结论（诚实）
    verdict = build_verdict(pooled, metrics)

    out = {
        "date": dt.date.today().isoformat(),
        "engine": "fib-trend",
        "universe": len(wl),
        "scanned": len(dfs),
        "failed": failed,
        "regime": regime_snapshot,
        "regime_gate": use_regime_gate,
        "config": {
            "n1": cfg.n1, "n2": cfg.n2, "m": cfg.m, "k": cfg.k,
            "label": cfg.label(),
            "kelly_fraction": cfg.kelly_fraction, "risk_per_trade": cfg.risk_per_trade,
            "require_slope": cfg.require_slope, "cost_roundtrip": cfg.cost_roundtrip,
        },
        "validation": {
            "pooled": pooled,
            "portfolio": metrics,
            "param_matrix": matrix,
            "slope_compare": slope_cmp,
            "verdict": verdict,
            "walkforward": oos,   # 样本外(OOS)诚实对照:is_pooled vs oos_pooled / oos_portfolio / verdict
        },
        "candidates": cands,
        "fresh_count": len(fresh),
        "rules": {
            "entry": f"EMA{cfg.n1} 上穿 EMA{cfg.n2}(金叉) + 收盘站上 EMA{cfg.m} + 慢线向上(真趋势) + ATR 过滤震荡",
            "stop": f"斐波那契硬止损 = 入场价 − {cfg.k}×ATR(14)",
            "exit": f"收盘 ≥ EMA{cfg.m} 一律持有(不主动止盈)；收盘 < EMA{cfg.m} 离场",
            "size": f"分数凯利({cfg.kelly_fraction:.0%}) · 单笔风险≤{cfg.risk_per_trade:.0%} · 单只≤{cfg.max_pos:.0%}",
        },
        "disclaimer": "研究参考工具，非投资建议。斐波那契趋势策略在震荡市必然连续小亏，靠少数大趋势"
                      "的非对称盈利覆盖；回测有效≠未来有效，宇宙为龙头精选存在事后选择偏差，"
                      "看『相对基准超额+回撤』才诚实。截断亏损、让利润奔跑，盈亏自负。",
        "updated_at": dt.datetime.now().isoformat(timespec="seconds"),
    }
    write_json([OUT_DIR / "fib_strategy.json", FRONT_DIR / "fib_strategy.json"], out)

    log("─" * 60)
    if pooled:
        log(f"池化：{pooled['trades']}笔 · 胜率{pooled['win_rate']}% · 盈亏比{pooled['payoff_ratio']} "
            f"· 期望R {pooled['expectancy_r']} · profit factor {pooled['profit_factor']}")
    if metrics:
        log(f"组合：总收益 {metrics['total_return']}% vs 基准 {metrics['bench_total']}% "
            f"(超额{metrics['excess']}%) · CAGR {metrics['cagr']}% · 回撤 {metrics['max_drawdown']}% "
            f"· 夏普 {metrics['sharpe']}")
    log(f"今日候选 {len(cands)} 只（新进场 {len(fresh)}）")
    log(f"结论：{verdict['headline']}")
    log(f"  → {OUT_DIR/'fib_strategy.json'}  &  {FRONT_DIR/'fib_strategy.json'}")


def build_verdict(pooled, metrics):
    """诚实给「策略是否有效」的结论。"""
    if not pooled or not metrics:
        return {"effective": False, "headline": "数据不足，无法判定有效性"}
    pf = pooled.get("profit_factor") or 0
    er = pooled.get("expectancy_r") or 0
    excess = metrics.get("excess", 0)
    effective = (er > 0) and (pf >= 1.1) and (excess > 0)
    if effective:
        head = (f"✅ 有效：期望每笔 +{er}R，profit factor {pf}（赚＞赔），"
                f"组合超额基准 +{excess}%。靠 {pooled['win_rate']}% 胜率 × {pooled['payoff_ratio']} 盈亏比"
                f"实现非对称收益——符合『截断亏损、让利润奔跑』。")
    elif er > 0 and pf >= 1.0:
        head = (f"⚠ 边际有效：期望 +{er}R、profit factor {pf}，但超额基准仅 {excess}%。"
                f"edge 偏弱，对成本/滑点敏感，建议缩小宇宙到强趋势品种。")
    else:
        head = (f"❌ 当前样本期无效：期望 {er}R、profit factor {pf}、超额 {excess}%。"
                f"多为震荡市，趋势策略本就吃亏；需配合趋势品种筛选或等趋势市再用。")
    return {"effective": effective, "profit_factor": pf, "expectancy_r": er,
            "excess": excess, "headline": head}


if __name__ == "__main__":
    main()
