# -*- coding: utf-8 -*-
"""
P3-A · 纸上交易引擎 (Paper Trading Engine)
═══════════════════════════════════════════════════════════════════════════════
把「选股信号」接成「可运维的实盘闭环」:持久化持仓台账 + 每日盯市 + 逐日盈亏对账。
这是「监控系统实盘运行状态」的核心——不下真单,但完整模拟一个账户每天的进出与净值,
让策略从「回测好看」走向「实盘可信」,并能与回测对账(live-vs-backtest)。

每日一次 run() 做四件事(无未来函数、按斐波规则、A股 T+1):
  ① 盯市离场:对每个在场持仓,用增量库最新 K 判出场——
       斐波硬止损(low≤stop0,跳空则以 min(open,stop0))/ 均线移动止损(close<EMA(m))。结算盈亏。
  ② 信号进场:读 fib_strategy.json 的今日 fresh_entry 候选,在「现金够+未满仓+未持有」时按单笔风险开仓。
  ③ 盯市估值:用最新收盘给在场持仓估值,算账户总净值。
  ④ 落账:净值点入库、台账持久化(JSON,人类可读)。同一交易日不重复处理(幂等)。

台账:data/paper_ledger.json。用法:
  python paper_trade.py run        # 推进一天(盘后调度调用)
  python paper_trade.py report     # 看持仓/已平/净值曲线
  python paper_trade.py reset      # 清空台账重来(起始资金 START_CAPITAL)
"""
import sys
import json
import datetime as dt
from pathlib import Path

import pandas as pd

import datastore as ds
from fib_engine import FibConfig, ema, atr_wilder

BASE = Path(__file__).resolve().parent
LEDGER = BASE / "data" / "paper_ledger.json"
STRATEGY_JSON = BASE / "output" / "fib_strategy.json"

START_CAPITAL = 1_000_000.0    # 起始资金(纸面)
MAX_CONCURRENT = 6             # 最多并发持仓(与回测一致)
RISK_PER_TRADE = 0.02          # 单笔风险预算
MAX_POS = 0.30                 # 单只仓位上限
KELLY_FRACTION = 0.5
COST_ROUNDTRIP = 0.002

# ── P3-B 风控熔断参数 ──
MAX_DD_HALT = 0.15             # 账户从峰值回撤 > 15% → 熔断,停止新开仓(只盯市/离场)
MAX_PER_SECTOR = 2             # 单板块最多并发持仓数(强制行业分散,避免扎堆同赛道)
DELEVER_AFTER_LOSSES = 3       # 连续止损达 N 次 → 后续新仓自动减半(冷静期)
DELEVER_FACTOR = 0.5           # 减半系数
RELEVER_AFTER_WINS = 2         # 连续盈利达 M 次 → 恢复正常仓位


def log(m):
    print(f"[{dt.datetime.now():%H:%M:%S}] {m}", flush=True)


# ───────────────────────── 台账 ─────────────────────────
def _blank():
    return {"capital": START_CAPITAL, "cash": START_CAPITAL,
            "positions": [], "closed": [], "nav": [], "alerts": [], "last_date": None}


# ───────────────────────── P3-B 风控辅助 ─────────────────────────
def _peak_equity(led):
    return max([n["equity"] for n in led["nav"]] + [led["capital"]])


def _consec(led, want_loss=True):
    """末尾连续『止损/盈利』笔数(按已平仓时间序)。"""
    n = 0
    for c in reversed(led["closed"]):
        is_loss = c["pnl"] <= 0
        if is_loss == want_loss:
            n += 1
        else:
            break
    return n


def _alert(led, kind, msg, today):
    led.setdefault("alerts", []).append({"date": today, "kind": kind, "msg": msg})
    log(f"  ⚠ [{kind}] {msg}")


def load_ledger():
    if LEDGER.exists():
        try:
            return json.loads(LEDGER.read_text(encoding="utf-8"))
        except Exception:
            pass
    return _blank()


def save_ledger(led):
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    LEDGER.write_text(json.dumps(led, ensure_ascii=False, indent=2), encoding="utf-8")


# ───────────────────────── 出场判定(最新一根) ─────────────────────────
def _exit_check(code, pos, cfg):
    """用增量库最新一根 K 判出场。返回 (exit_price, reason) 或 (None,None) 继续持有。"""
    try:
        df = ds.get_hist(code, update=True)
    except Exception as e:
        log(f"  {code} 取价失败,保持持有:{type(e).__name__}")
        return None, None
    if df.empty:
        return None, None
    last_date = df.index[-1].strftime("%Y-%m-%d")
    if last_date <= pos["entry_date"]:      # T+1:进场当日(或更早数据)不出场
        return None, None
    emam = ema(df["close"], cfg.m)
    row = df.iloc[-1]
    o, lo, c = float(row["open"]), float(row["low"]), float(row["close"])
    em = float(emam.iloc[-1])
    stop0 = pos["stop0"]
    if lo <= stop0:                         # 斐波硬止损(盘中)
        return (min(o, stop0) if o < stop0 else stop0), "fib_stop"
    if c < em:                              # 均线移动止损(收盘)
        return c, "ma_break"
    return None, None


# ───────────────────────── 进场 ─────────────────────────
def _open_positions(led, cfg, today, size_factor=1.0):
    if not STRATEGY_JSON.exists():
        log("  无 fib_strategy.json,跳过进场(先跑 fib_scan)")
        return
    strat = json.loads(STRATEGY_JSON.read_text(encoding="utf-8"))
    held = {p["code"] for p in led["positions"]}
    # P4 AI 否决:读 ai_veto.json,被 AI 判定利空的票直接不开仓(技术面进攻 + AI 排雷)
    veto_set = set()
    vj = BASE / "output" / "ai_veto.json"
    if vj.exists():
        try:
            veto_set = set(json.loads(vj.read_text(encoding="utf-8")).get("vetoed", []))
        except Exception:
            pass
    # 板块敞口:统计在场各板块持仓数(强制分散)
    sec_count = {}
    for p in led["positions"]:
        sec_count[p.get("sector", "")] = sec_count.get(p.get("sector", ""), 0) + 1
    fresh = [c for c in strat.get("candidates", []) if c.get("state") == "fresh_entry"]
    for cand in fresh:
        if len(led["positions"]) >= MAX_CONCURRENT:
            break
        code = cand["code"]
        if code in held:
            continue
        if code in veto_set:                # AI 否决的票不开仓
            log(f"  ⊘ 跳过 {code} {cand.get('name','')}(AI 排雷否决)")
            continue
        sec = cand.get("sector", "") or "其他"
        # 板块敞口闸:仅在行业已知时生效(数据缺行业时不惩罚,避免全归「其他」被误限)
        if sec != "其他" and sec_count.get(sec, 0) >= MAX_PER_SECTOR:
            continue
        entry = float(cand["entry"])
        stop0 = float(cand["fib_stop"])
        if entry <= 0 or stop0 <= 0 or stop0 >= entry:
            continue
        init_risk = (entry - stop0) / entry
        pos_frac = min(RISK_PER_TRADE / max(init_risk, 0.005), MAX_POS) * KELLY_FRACTION * size_factor
        alloc = led["cash"] * pos_frac
        if alloc < entry * 100:             # 不足 1 手
            continue
        shares = int(alloc / entry // 100) * 100
        if shares < 100:
            continue
        cost = shares * entry
        led["cash"] -= cost * (1 + COST_ROUNDTRIP / 2)
        led["positions"].append({
            "code": code, "name": cand.get("name", code), "sector": sec,
            "entry_date": today, "entry": round(entry, 3), "shares": shares,
            "stop0": round(stop0, 3), "trail_ma": cand.get("trail_ma_label", f"EMA{cfg.m}"),
            "cost": round(cost, 2),
        })
        held.add(code)
        sec_count[sec] = sec_count.get(sec, 0) + 1
        log(f"  + 开仓 {code} {cand.get('name','')} {shares}股 @ {entry}  止损 {stop0}"
            + (f"  [{sec}·减半]" if size_factor < 1 else f"  [{sec}]"))


# ───────────────────────── 盯市 + 主流程 ─────────────────────────
def _mark_to_market(led, cfg):
    """用最新收盘给在场持仓估值,返回 (持仓市值, {code:close})。"""
    pv, prices = 0.0, {}
    for p in led["positions"]:
        try:
            df = ds.get_hist(p["code"], update=False)
            c = float(df["close"].iloc[-1])
        except Exception:
            c = p["entry"]
        prices[p["code"]] = c
        pv += p["shares"] * c
    return pv, prices


def run():
    cfg = FibConfig()
    led = load_ledger()
    today = dt.date.today().isoformat()
    if led["last_date"] == today:
        log(f"今日 {today} 已处理过(幂等),跳过。用 report 查看。")
        return
    log(f"纸上交易 · 推进至 {today} · 在场 {len(led['positions'])} 持仓 · 现金 {led['cash']:,.0f}")

    # ① 盯市离场
    still = []
    for p in led["positions"]:
        ex, reason = _exit_check(p["code"], p, cfg)
        if ex is None:
            still.append(p)
            continue
        proceeds = p["shares"] * ex * (1 - COST_ROUNDTRIP / 2)
        pnl = proceeds - p["cost"]
        r_mult = (ex / p["entry"] - 1) / ((p["entry"] - p["stop0"]) / p["entry"]) if p["entry"] > p["stop0"] else 0
        led["cash"] += proceeds
        led["closed"].append({**p, "exit_date": today, "exit": round(ex, 3),
                              "reason": reason, "pnl": round(pnl, 2), "r_multiple": round(r_mult, 2)})
        log(f"  - 平仓 {p['code']} {p['name']} @ {ex:.3f} [{reason}] 盈亏 {pnl:+,.0f} ({r_mult:+.2f}R)")
    led["positions"] = still

    # ②a 风控熔断:离场后先估值,算从峰值的回撤
    pv0, _ = _mark_to_market(led, cfg)
    equity0 = led["cash"] + pv0
    peak = _peak_equity(led)
    dd = equity0 / peak - 1 if peak else 0.0
    halted = dd <= -MAX_DD_HALT
    losses = _consec(led, want_loss=True)
    wins = _consec(led, want_loss=False)
    size_factor = DELEVER_FACTOR if (losses >= DELEVER_AFTER_LOSSES and wins < RELEVER_AFTER_WINS) else 1.0

    # ② 信号进场(熔断时停开新仓;连损期减半)
    if halted:
        _alert(led, "熔断", f"账户回撤 {dd:.1%} 超阈值 {-MAX_DD_HALT:.0%},暂停新开仓(只盯市/离场)", today)
    else:
        if size_factor < 1.0:
            _alert(led, "连损减仓", f"连续止损 {losses} 次,新仓位减半冷静", today)
        _open_positions(led, cfg, today, size_factor=size_factor)

    # ③ 盯市估值 + ④ 落账
    pv, _ = _mark_to_market(led, cfg)
    equity = led["cash"] + pv
    led["nav"].append({"date": today, "equity": round(equity, 2),
                       "cash": round(led["cash"], 2), "pos_value": round(pv, 2),
                       "n_open": len(led["positions"]),
                       "drawdown": round(equity / _peak_equity(led) - 1, 4),
                       "halted": halted})
    led["last_date"] = today
    save_ledger(led)

    ret = equity / led["capital"] - 1
    log(f"账户净值 {equity:,.0f}(累计 {ret:+.2%})· 在场 {len(led['positions'])} · 已平 {len(led['closed'])} 笔")
    log(f"  → 台账 {LEDGER}")


def report():
    led = load_ledger()
    print("═" * 76)
    print(f"纸上交易账户 · 起始 {led['capital']:,.0f} · 最近处理 {led.get('last_date','—')}")
    if led["nav"]:
        last = led["nav"][-1]
        ret = last["equity"] / led["capital"] - 1
        dd = last.get("drawdown", 0)
        flag = " 🔴熔断中" if last.get("halted") else ""
        print(f"当前净值 {last['equity']:,.0f}（{ret:+.2%}）· 回撤 {dd:+.1%}{flag} · "
              f"现金 {last['cash']:,.0f} · 持仓市值 {last['pos_value']:,.0f}")
    alerts = led.get("alerts", [])
    if alerts:
        print(f"风控告警 {len(alerts)} 条(近 5):")
        for a in alerts[-5:]:
            print(f"  {a['date']} [{a['kind']}] {a['msg']}")
    print("─" * 76)
    print(f"在场持仓 {len(led['positions'])}:")
    for p in led["positions"]:
        print(f"  {p['code']} {p['name']:<8} {p['shares']}股 @ {p['entry']} 止损 {p['stop0']} ({p['entry_date']})")
    print(f"已平仓 {len(led['closed'])}:")
    wins = [c for c in led["closed"] if c["pnl"] > 0]
    for c in led["closed"][-10:]:
        print(f"  {c['code']} {c['name']:<8} {c['entry_date']}→{c['exit_date']} "
              f"[{c['reason']}] {c['pnl']:+,.0f} ({c['r_multiple']:+.2f}R)")
    if led["closed"]:
        tot = sum(c["pnl"] for c in led["closed"])
        print(f"  合计已实现盈亏 {tot:+,.0f} · 胜率 {len(wins)/len(led['closed'])*100:.0f}%")
    print("═" * 76)


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    if cmd == "reset":
        save_ledger(_blank())
        log(f"台账已重置 · 起始资金 {START_CAPITAL:,.0f}")
    elif cmd == "report":
        report()
    else:
        run()


if __name__ == "__main__":
    main()
