# -*- coding: utf-8 -*-
"""
P3-C · 可观测监控 (Observability / Health Dashboard)
═══════════════════════════════════════════════════════════════════════════════
把整条量化流水线的运行状态汇成一个「每日健康面板」——「监控系统实盘运行状态」的落点。
检查四层并给 ✅/⚠/❌ 评级,任何一层异常都能一眼看到、可告警、可恢复:

  ① 数据层:增量库股票数 / 最新数据日 / 数据陈旧度(距今多少交易日)
  ② 策略层:fib_strategy.json 产出日期 / 今日候选数 / 样本外(OOS)有效性结论
  ③ 账户层:纸上账户净值 / 累计收益 / 回撤 / 在场持仓 / 是否熔断
  ④ 风控层:近期风控告警(熔断 / 连损减仓)

产出 output/monitor_status.json(+同步前端目录),供 App 顶部「系统状态」灯渲染。
用法:python monitor.py            # 打印面板 + 落 status.json
"""
import json
import datetime as dt
from pathlib import Path

BASE = Path(__file__).resolve().parent
OUT_DIR = BASE / "output"
FRONT_DIR = BASE.parent / "polaris-app" / "public" / "sentio"
STRATEGY_JSON = OUT_DIR / "fib_strategy.json"
LEDGER = BASE / "data" / "paper_ledger.json"

STALE_DAYS = 5     # 数据最新日距今 > N 自然日 → 告警(覆盖周末/小长假)


def _load(p):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:
        return None


def _days_since(date_str):
    try:
        d = dt.date.fromisoformat(str(date_str)[:10])
        return (dt.date.today() - d).days
    except Exception:
        return None


def check_data():
    try:
        import datastore as ds
        s = ds.stats()
    except Exception as e:
        return {"sev": "err", "msg": f"增量库读取失败:{type(e).__name__}", "detail": {}}
    rng = s.get("date_range", "空")
    last = rng.split("→")[-1] if "→" in rng else None
    stale = _days_since(last)
    sev = "ok"
    msg = f"库内 {s['stocks']} 只 / {s['rows']:,} 行 / 最新 {last}"
    if s["stocks"] == 0:
        sev, msg = "err", "增量库为空(先 datastore.py migrate / update)"
    elif stale is not None and stale > STALE_DAYS:
        sev, msg = "warn", f"数据陈旧:最新 {last}(距今 {stale} 天),需更新"
    return {"sev": sev, "msg": msg, "detail": s}


def check_strategy():
    strat = _load(STRATEGY_JSON)
    if not strat:
        return {"sev": "err", "msg": "无 fib_strategy.json(先跑 fib_scan)", "detail": {}}
    date = strat.get("date")
    stale = _days_since(date)
    cands = len(strat.get("candidates", []))
    fresh = strat.get("fresh_count", 0)
    wf = (strat.get("validation", {}) or {}).get("walkforward")
    oos = None
    if wf and wf.get("verdict"):
        oos = wf["verdict"].get("headline")
    sev = "ok"
    msg = f"产出 {date} · 候选 {cands} 只(新进场 {fresh})"
    if stale is not None and stale > STALE_DAYS:
        sev, msg = "warn", f"策略产出陈旧:{date}(距今 {stale} 天),需重跑 fib_scan"
    return {"sev": sev, "msg": msg, "detail": {"date": date, "candidates": cands,
            "fresh": fresh, "oos_verdict": oos}}


def check_account():
    led = _load(LEDGER)
    if not led or not led.get("nav"):
        return {"sev": "warn", "msg": "纸上账户未初始化(先 paper_trade.py run)", "detail": {}}
    last = led["nav"][-1]
    cap = led.get("capital", 1)
    ret = last["equity"] / cap - 1
    dd = last.get("drawdown", 0)
    halted = last.get("halted", False)
    nclosed = len(led.get("closed", []))
    wins = sum(1 for c in led.get("closed", []) if c["pnl"] > 0)
    wr = (wins / nclosed * 100) if nclosed else None
    sev = "ok"
    msg = (f"净值 {last['equity']:,.0f}({ret:+.2%})· 回撤 {dd:+.1%} · "
           f"在场 {last['n_open']} · 已平 {nclosed}" + (f" · 胜率 {wr:.0f}%" if wr is not None else ""))
    if halted:
        sev, msg = "err", "🔴 风控熔断中:账户回撤超阈值,已停止新开仓"
    elif dd <= -0.10:
        sev, msg = "warn", msg + " · 回撤偏深,留意"
    return {"sev": sev, "msg": msg, "detail": {"equity": last["equity"], "ret": round(ret, 4),
            "drawdown": dd, "halted": halted, "n_open": last["n_open"], "closed": nclosed}}


def check_alerts():
    led = _load(LEDGER) or {}
    alerts = led.get("alerts", [])
    recent = [a for a in alerts if (_days_since(a["date"]) or 99) <= 7]
    if not recent:
        return {"sev": "ok", "msg": "近 7 日无风控告警", "detail": {"alerts": []}}
    return {"sev": "warn", "msg": f"近 7 日 {len(recent)} 条风控告警",
            "detail": {"alerts": recent[-5:]}}


SEV_ICON = {"ok": "✅", "warn": "⚠", "err": "❌"}
SEV_RANK = {"ok": 0, "warn": 1, "err": 2}


def main():
    checks = {
        "数据层": check_data(),
        "策略层": check_strategy(),
        "账户层": check_account(),
        "风控层": check_alerts(),
    }
    worst = max((SEV_RANK[c["sev"]] for c in checks.values()), default=0)
    overall = ["健康", "注意", "异常"][worst]
    oicon = SEV_ICON[["ok", "warn", "err"][worst]]

    print("═" * 68)
    print(f"  SENTIO 量化系统 · 健康面板  {oicon} 总体:{overall}   {dt.datetime.now():%Y-%m-%d %H:%M}")
    print("═" * 68)
    for name, c in checks.items():
        print(f"  {SEV_ICON[c['sev']]} {name}：{c['msg']}")
    oos = checks["策略层"]["detail"].get("oos_verdict")
    if oos:
        print("  " + "─" * 60)
        print(f"  📊 样本外结论：{oos}")
    print("═" * 68)

    status = {
        "overall": overall,
        "overall_sev": ["ok", "warn", "err"][worst],
        "checks": {k: {"sev": v["sev"], "msg": v["msg"], "detail": v["detail"]} for k, v in checks.items()},
        "updated_at": dt.datetime.now().isoformat(timespec="seconds"),
    }
    for p in (OUT_DIR / "monitor_status.json", FRONT_DIR / "monitor_status.json"):
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  → {OUT_DIR / 'monitor_status.json'}  (+前端)")


if __name__ == "__main__":
    main()
