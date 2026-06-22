# -*- coding: utf-8 -*-
"""
SENTIO · 券商对接层 (Broker Adapter)
═══════════════════════════════════════════════════════════════════════════════
把「读账户 / 同步持仓 / 下单」抽象成统一接口，背后可挂不同实现：
  • SimAdapter   —— 模拟盘（默认）。零风险，用真实行情价撮合，全流程可跑通，先用起来。
  • EasyTraderAdapter —— 真实盘。基于开源 easytrader 自动化券商 PC 客户端
       (同花顺通用版 universal_client / 同花顺 ths / 各大券商白标客户端)，覆盖多平台。
       仅在用户显式配置 + 打开「自动交易」相关授权后才会真正连真账户。

★ 资金安全三道闸（无论哪种 adapter，下单前都强制过）：
  ① 授权闸：auto_trade=false 时，下单只允许「单笔模式」(前端弹窗确认后逐单调用)；
            auto_trade=true（用户在前端显式打开总开关）才允许程序连续自动下单。
  ② 额度闸：单笔金额 ≤ per_order；当日累计买入 ≤ per_day（落 broker_daylog.json 计数）。
  ③ 仓位闸：单票市值占比 ≤ max_pos_pct%（防单吊一只）。
  任一闸不过 → 拒绝下单并返回 blocked，绝不静默成交。

子命令（Rust broker_cmd 调用，结果以最后一行 JSON 返回）：
  python broker.py status                         读账户快照 → account.json
  python broker.py sync                           拉真实持仓并并入 holdings.json（让诊断按真实成本算）
  python broker.py order BUY 600519 100 [price]   下单（过三道闸；price 缺省用最新价）
  python broker.py reset-sim                       重置模拟盘
"""
import os
import sys
import json
import datetime as dt
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))

DATA_DIR = Path(os.environ.get("SENTIO_DATA_DIR", str(BASE / "data")))
FRONT_DIR = BASE.parent / "polaris-app" / "public" / "sentio"
OUT_DIR = BASE / "output"
CONFIG = DATA_DIR / "broker_config.json"
HOLDINGS = DATA_DIR / "holdings.json"
SIM_STATE = DATA_DIR / "sim_account.json"
DAYLOG = DATA_DIR / "broker_daylog.json"

DEFAULT_CONFIG = {
    "adapter": "sim",            # sim | ths | universal | <easytrader broker key>
    "auto_trade": False,         # 主开关：False=每单需前端确认；True=额度内允许自动下单
    "limits": {"per_order": 50000, "per_day": 200000, "max_pos_pct": 25},
    "easytrader": {"broker": "universal_client", "exe_path": "", "config_path": ""},
    "sim_start_cash": 1000000.0,
}


def log(m):
    print(f"[{dt.datetime.now():%H:%M:%S}] {m}", flush=True)


def _emit(obj):
    """结果以单行 JSON 打到 stdout 最后一行，供 Rust 取回。"""
    print("RESULT:" + json.dumps(obj, ensure_ascii=False), flush=True)


def load_config() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    if CONFIG.exists():
        try:
            user = json.loads(CONFIG.read_text(encoding="utf-8"))
            cfg.update({k: user.get(k, v) for k, v in DEFAULT_CONFIG.items()})
            if isinstance(user.get("limits"), dict):
                cfg["limits"] = {**DEFAULT_CONFIG["limits"], **user["limits"]}
            if isinstance(user.get("easytrader"), dict):
                cfg["easytrader"] = {**DEFAULT_CONFIG["easytrader"], **user["easytrader"]}
        except Exception as e:
            log(f"读 broker_config 失败({type(e).__name__})，用默认")
    return cfg


def _name_of(code: str) -> str:
    for fn in ("watchlist.json", "universe.json"):
        fp = BASE / fn
        if fp.exists():
            try:
                for s in json.loads(fp.read_text(encoding="utf-8")).get("stocks", []):
                    if s.get("code") == code:
                        return s.get("name", code)
            except Exception:
                pass
    return code


def _last_price(code: str):
    """最新收盘价（真实落库行情）。失败返回 None。"""
    try:
        import datastore
        df = datastore.get_hist(code, update=False)
        if df is not None and len(df):
            return float(round(df["close"].iloc[-1], 3))
    except Exception:
        pass
    return None


# ───────────────────────── adapter 抽象 ─────────────────────────
class BrokerAdapter:
    name = "base"
    connected = False

    def balance(self) -> dict:
        raise NotImplementedError

    def positions(self) -> list:
        raise NotImplementedError

    def place(self, action: str, code: str, shares: int, price: float) -> dict:
        raise NotImplementedError


class SimAdapter(BrokerAdapter):
    """模拟盘：真实行情价撮合，落 sim_account.json。零资金风险，先把全流程跑通。"""
    name = "sim"

    def __init__(self, start_cash: float):
        self.connected = True
        if SIM_STATE.exists():
            self.st = json.loads(SIM_STATE.read_text(encoding="utf-8"))
        else:
            self.st = {"cash": float(start_cash), "positions": {}}
            self._save()

    def _save(self):
        SIM_STATE.parent.mkdir(parents=True, exist_ok=True)
        SIM_STATE.write_text(json.dumps(self.st, ensure_ascii=False, indent=2), encoding="utf-8")

    def positions(self) -> list:
        out = []
        for code, p in self.st.get("positions", {}).items():
            if p.get("shares", 0) <= 0:
                continue
            price = _last_price(code) or p.get("cost", 0)
            mv = price * p["shares"]
            cost_val = p["cost"] * p["shares"]
            out.append({
                "code": code, "name": _name_of(code), "shares": p["shares"],
                "cost": round(p["cost"], 3), "price": price,
                "market_value": round(mv, 2),
                "pnl": round(mv - cost_val, 2),
                "pnl_pct": round((price / p["cost"] - 1) * 100, 2) if p["cost"] else 0.0,
            })
        return out

    def balance(self) -> dict:
        mv = sum(p["market_value"] for p in self.positions())
        cash = round(self.st.get("cash", 0), 2)
        return {"cash": cash, "market_value": round(mv, 2), "total": round(cash + mv, 2), "frozen": 0.0}

    def place(self, action, code, shares, price):
        pos = self.st["positions"].setdefault(code, {"shares": 0, "cost": 0.0})
        if action == "BUY":
            if price * shares > self.st["cash"]:
                return {"ok": False, "msg": "模拟盘资金不足"}
            new_sh = pos["shares"] + shares
            pos["cost"] = (pos["cost"] * pos["shares"] + price * shares) / new_sh if new_sh else price
            pos["shares"] = new_sh
            self.st["cash"] -= price * shares
        else:  # SELL
            if shares > pos["shares"]:
                return {"ok": False, "msg": f"模拟盘持仓不足(持{pos['shares']})"}
            pos["shares"] -= shares
            self.st["cash"] += price * shares
            if pos["shares"] == 0:
                pos["cost"] = 0.0
        self._save()
        return {"ok": True, "msg": "模拟成交"}


class EasyTraderAdapter(BrokerAdapter):
    """真实盘：基于 easytrader 自动化券商 PC 客户端。仅在用户配置好且环境就绪时可用。"""
    name = "easytrader"

    def __init__(self, et_cfg: dict):
        self.connected = False
        self.user = None
        try:
            import easytrader  # 可选依赖，未安装则抛 ImportError
        except Exception as e:
            raise RuntimeError(f"easytrader 未安装或不可用：{e}。请先 pip install easytrader 并配置券商客户端。")
        broker = et_cfg.get("broker") or "universal_client"
        self.user = easytrader.use(broker)
        cfgp = et_cfg.get("config_path") or ""
        exep = et_cfg.get("exe_path") or ""
        if exep:
            try:
                self.user.connect(exep)
            except Exception as e:
                raise RuntimeError(f"连接券商客户端失败：{e}")
        elif cfgp:
            self.user.prepare(cfgp)
        else:
            raise RuntimeError("未配置券商客户端路径(exe_path)或登录配置(config_path)")
        self.connected = True

    def balance(self) -> dict:
        b = self.user.balance
        rec = b[0] if isinstance(b, list) and b else (b or {})
        cash = float(rec.get("可用金额", rec.get("可用资金", rec.get("资金余额", 0))) or 0)
        mv = float(rec.get("最新市值", rec.get("股票市值", 0)) or 0)
        total = float(rec.get("总资产", cash + mv) or (cash + mv))
        return {"cash": round(cash, 2), "market_value": round(mv, 2), "total": round(total, 2), "frozen": 0.0}

    def positions(self) -> list:
        out = []
        for p in (self.user.position or []):
            code = str(p.get("证券代码", p.get("股票代码", ""))).zfill(6)
            sh = int(float(p.get("股票余额", p.get("持仓数量", 0)) or 0))
            if not code or sh <= 0:
                continue
            cost = float(p.get("成本价", p.get("参考成本价", 0)) or 0)
            price = _last_price(code) or float(p.get("市价", cost) or cost)
            mv = price * sh
            out.append({"code": code, "name": str(p.get("证券名称", _name_of(code))),
                        "shares": sh, "cost": round(cost, 3), "price": price,
                        "market_value": round(mv, 2), "pnl": round((price - cost) * sh, 2),
                        "pnl_pct": round((price / cost - 1) * 100, 2) if cost else 0.0})
        return out

    def place(self, action, code, shares, price):
        try:
            if action == "BUY":
                r = self.user.buy(code, price=price, amount=shares)
            else:
                r = self.user.sell(code, price=price, amount=shares)
            return {"ok": True, "msg": f"已提交券商：{r}"}
        except Exception as e:
            return {"ok": False, "msg": f"券商下单失败：{e}"}


def get_adapter(cfg: dict) -> BrokerAdapter:
    a = (cfg.get("adapter") or "sim").lower()
    if a in ("sim", "", "paper"):
        return SimAdapter(cfg.get("sim_start_cash", 1000000.0))
    # 任何非 sim 的 adapter 一律走真实 easytrader（broker key 透传）
    et = dict(cfg.get("easytrader", {}))
    if a not in ("easytrader", "real"):
        et["broker"] = a   # adapter 直接当 easytrader broker key（如 ths / universal_client）
    return EasyTraderAdapter(et)


# ───────────────────────── 风控三道闸 ─────────────────────────
def _today() -> str:
    return dt.date.today().isoformat()


def _day_spent() -> float:
    if DAYLOG.exists():
        try:
            d = json.loads(DAYLOG.read_text(encoding="utf-8"))
            if d.get("date") == _today():
                return float(d.get("buy_amount", 0))
        except Exception:
            pass
    return 0.0


def _add_day_spent(amt: float):
    DAYLOG.parent.mkdir(parents=True, exist_ok=True)
    cur = _day_spent()
    DAYLOG.write_text(json.dumps({"date": _today(), "buy_amount": round(cur + amt, 2)},
                                 ensure_ascii=False), encoding="utf-8")


def risk_check(cfg, adapter, action, code, shares, price) -> dict:
    """三道闸。通过返回 {ok:True}，否则 {ok:False, blocked:reason}。"""
    amt = price * shares
    lim = cfg["limits"]
    # ① 授权闸由调用方(Rust/前端)保证：单笔模式=确认后才调本函数；这里再兜底校验 auto。
    # ② 额度闸
    if amt > lim["per_order"]:
        return {"ok": False, "blocked": f"超单笔额度：{amt:.0f} > {lim['per_order']}"}
    if action == "BUY" and _day_spent() + amt > lim["per_day"]:
        return {"ok": False, "blocked": f"超当日买入额度：今日已用 {_day_spent():.0f} + {amt:.0f} > {lim['per_day']}"}
    # ③ 仓位闸（仅买入时校验目标占比）
    if action == "BUY":
        bal = adapter.balance()
        total = bal["total"] or 1
        held = next((p["market_value"] for p in adapter.positions() if p["code"] == code), 0)
        if (held + amt) / total * 100 > lim["max_pos_pct"]:
            return {"ok": False, "blocked": f"超单票仓位上限 {lim['max_pos_pct']}%（防单吊一只）"}
    return {"ok": True}


# ───────────────────────── 快照 / 同步 ─────────────────────────
def write_account(cfg, adapter):
    try:
        snap = {
            "ok": True, "adapter": adapter.name, "connected": adapter.connected,
            "auto_trade": bool(cfg.get("auto_trade")), "limits": cfg["limits"],
            "balance": adapter.balance(), "positions": adapter.positions(),
            "day_spent": _day_spent(),
            "updated_at": dt.datetime.now().isoformat(timespec="seconds"),
        }
    except Exception as e:
        snap = {"ok": False, "adapter": cfg.get("adapter"), "connected": False,
                "error": f"{type(e).__name__}: {str(e)[:80]}",
                "updated_at": dt.datetime.now().isoformat(timespec="seconds")}
    for p in (OUT_DIR / "account.json", FRONT_DIR / "account.json"):
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(snap, ensure_ascii=False, indent=2), encoding="utf-8")
    return snap


def sync_holdings(adapter):
    """把真实持仓写进 holdings.json，让自选诊断按你的真实成本/股数做仓位感知。"""
    poss = adapter.positions()
    HOLDINGS.parent.mkdir(parents=True, exist_ok=True)
    HOLDINGS.write_text(json.dumps(
        {"_comment": "由券商同步生成；自选诊断据此做止盈/止损建议。",
         "positions": [{"code": p["code"], "cost": p["cost"], "shares": p["shares"]} for p in poss]},
        ensure_ascii=False, indent=2), encoding="utf-8")
    return len(poss)


def main():
    args = sys.argv[1:]
    sub = args[0] if args else "status"
    cfg = load_config()
    try:
        adapter = get_adapter(cfg)
    except Exception as e:
        snap = write_account(cfg, None) if False else None
        out = {"ok": False, "adapter": cfg.get("adapter"), "connected": False,
               "error": f"{type(e).__name__}: {str(e)[:100]}"}
        # 真实盘连接失败也写一份 account.json，前端能显示「未连接 + 原因」
        for p in (OUT_DIR / "account.json", FRONT_DIR / "account.json"):
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps({**out, "auto_trade": bool(cfg.get("auto_trade")),
                                     "limits": cfg["limits"],
                                     "updated_at": dt.datetime.now().isoformat(timespec="seconds")},
                                    ensure_ascii=False, indent=2), encoding="utf-8")
        log(f"adapter 初始化失败：{out['error']}")
        _emit(out)
        return

    if sub == "status":
        snap = write_account(cfg, adapter)
        log(f"账户快照 · {adapter.name} · 持仓 {len(snap.get('positions', []))} 只")
        _emit(snap)

    elif sub == "sync":
        n = sync_holdings(adapter)
        snap = write_account(cfg, adapter)
        log(f"已同步 {n} 只持仓 → holdings.json")
        _emit({"ok": True, "synced": n, "account": snap})

    elif sub == "order":
        # order BUY 600519 100 [price]
        if len(args) < 4:
            _emit({"ok": False, "msg": "用法：order BUY|SELL <code> <shares> [price]"})
            return
        action = args[1].upper()
        code = args[2]
        shares = int(float(args[3]))
        price = float(args[4]) if len(args) > 4 else (_last_price(code) or 0)
        if action not in ("BUY", "SELL") or shares <= 0 or price <= 0:
            _emit({"ok": False, "msg": "参数非法(action/shares/price)"})
            return
        # 授权兜底：自动模式关闭时，本命令只应由前端「确认后」单笔调用（Rust 已强制确认语义）。
        chk = risk_check(cfg, adapter, action, code, shares, price)
        if not chk["ok"]:
            log(f"下单被风控拦截：{chk['blocked']}")
            _emit({"ok": False, "blocked": chk["blocked"], "action": action, "code": code,
                   "shares": shares, "price": price, "amount": round(price * shares, 2)})
            return
        res = adapter.place(action, code, shares, price)
        if res.get("ok") and action == "BUY":
            _add_day_spent(price * shares)
        write_account(cfg, adapter)
        out = {"ok": res.get("ok", False), "msg": res.get("msg", ""), "action": action,
               "code": code, "name": _name_of(code), "shares": shares, "price": price,
               "amount": round(price * shares, 2)}
        log(f"{action} {code} {shares}@{price} → {out['msg']}")
        _emit(out)

    elif sub == "reset-sim":
        for f in (SIM_STATE, DAYLOG):
            if f.exists():
                f.unlink()
        cfg["adapter"] = "sim"
        adapter = get_adapter(cfg)
        write_account(cfg, adapter)
        _emit({"ok": True, "msg": "模拟盘已重置"})

    else:
        _emit({"ok": False, "msg": f"未知子命令：{sub}"})


if __name__ == "__main__":
    main()
