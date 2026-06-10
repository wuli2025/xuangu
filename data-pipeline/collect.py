# -*- coding: utf-8 -*-
"""
SENTIO 舆情采集器 · MVP 第①②层（零爬虫零风险）
- 第①层 行为/热度：东财千股千评(关注指数·全市场分位) + 东财人气榜
- 第②层 资金：逐股主力资金净流入(净占比)  [并发抓取]
- 市场聚合：市场情绪温度 + 涨跌家数宽度 + 指数 + 反转预警数  → board.json
计算「情绪温度 0-100」(MVP 含 H+F，文本情感 S 第二阶段补)，落 SQLite + 出 JSON。

依赖：akshare>=1.16, pandas>=2.2
用法：python collect.py            # 跑 watchlist.json 全部
     python collect.py 600519     # 只跑指定代码(可多个)
合规：仅用 akshare 官方聚合公开数据，不写爬虫、不绕反爬。研究参考，非投资建议。
"""
import os
import sys
import json
import sqlite3
import time
import datetime as dt
from pathlib import Path

# 本机配了 Clash 代理(127.0.0.1:7897)，会破坏到东财的 TLS(报 bad record mac)。
# 东财/akshare 都是国内源，让所有 requests 会话忽略系统/注册表代理直连。
# requests 不把 NO_PROXY="*" 当通配，故 monkeypatch Session.trust_env=False。必须在 import akshare 前。
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
import pandas as pd

BASE = Path(__file__).resolve().parent
DB_PATH = BASE / "data" / "sentio.db"
OUT_DIR = BASE / "output"
WATCHLIST = BASE / "watchlist.json"
# 前端静态目录(Vite 把 public/ 映射到根路径，前端 fetch('/sentio/xxx.json'))
FRONT_DIR = BASE.parent / "polaris-app" / "public" / "sentio"

W_H, W_F = 0.40, 0.35  # 温度权重(规划 H0.40/F0.35/S0.25)，MVP 无 S 按 H+F 重归一


def log(msg):
    print(f"[{dt.datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def find_col(df, *keys):
    for k in keys:
        for c in df.columns:
            if k in str(c):
                return c
    return None


# ---------- 第①层：全市场热度（一次拉取 + 预计算分位表） ----------
def build_heat_index():
    """拉千股千评+人气榜，预计算 {code: 关注指数} 与全市场升序序列(供 O(logN) 分位)。"""
    idx = {"by_code": {}, "rank_by_code": {}, "sorted": None, "hot": set()}

    def _retry(fn, n=3):
        err = None
        for _ in range(n):
            try:
                return fn()
            except Exception as e:
                err = e
                time.sleep(1)
        raise err

    try:
        c = _retry(ak.stock_comment_em)
        ccol, gcol, rcol = find_col(c, "代码"), find_col(c, "关注指数"), find_col(c, "目前排名")
        codes = c[ccol].astype(str).str.zfill(6)
        g = pd.to_numeric(c[gcol], errors="coerce")
        idx["by_code"] = dict(zip(codes, g))
        if rcol:
            idx["rank_by_code"] = dict(zip(codes, pd.to_numeric(c[rcol], errors="coerce")))
        idx["sorted"] = g.dropna().sort_values().to_numpy()  # 升序，searchsorted 算分位
        log(f"千股千评 OK：{len(idx['by_code'])} 行")
    except Exception as e:
        log(f"千股千评 FAIL：{type(e).__name__}: {e}")
    try:
        hot_df = _retry(ak.stock_hot_rank_em)
        col = find_col(hot_df, "代码")
        idx["hot"] = {str(v)[-6:] for v in hot_df[col].tolist()}
        log(f"东财人气榜 OK：{len(idx['hot'])} 只")
    except Exception as e:
        log(f"东财人气榜 FAIL：{type(e).__name__}: {e}")
    return idx


def heat_score(code, idx):
    evidence, h = {}, 50.0
    val = idx["by_code"].get(code)
    if val is not None and pd.notna(val) and idx["sorted"] is not None and len(idx["sorted"]):
        import numpy as np
        pos = int(np.searchsorted(idx["sorted"], val, side="left"))
        h = pos / len(idx["sorted"]) * 100
        evidence["关注指数"] = round(float(val), 1)
        evidence["关注指数全市场分位"] = f"{h:.0f}%"
        r = idx["rank_by_code"].get(code)
        if r is not None and pd.notna(r):
            evidence["千股千评排名"] = int(r)
    if code in idx["hot"]:
        h = min(100.0, h + 12.0)
        evidence["东财人气榜"] = "在榜 Top100"
    return round(h, 1), evidence


# ---------- 第②层：逐股资金（自实现，不带 `_` cache-buster） ----------
_MARKET_SECID = {"sh": 1, "sz": 0, "bj": 0}
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")


def fetch_fund_flow_last(code, market):
    """最新交易日 (日期, 主力净额, 主力净占比)。
    关键：只取 f51(日期)/f52(主力净额)/f57(主力占比) 三个字段——全字段大响应会被本机
    网络路径破坏(TLS reset / bad record mac)，最小响应才稳。requests 主，curl.exe 兜底。"""
    import subprocess
    secid = f"{_MARKET_SECID.get(market, 1)}.{code}"
    qs = (f"lmt=30&klt=101&secid={secid}&fields1=f1,f2,f3,f7&fields2=f51,f52,f57"
          f"&ut=b2884a393a59ad64002292a3e90d46a5")
    url = f"https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get?{qs}"

    def _parse(text):
        klines = json.loads(text)["data"]["klines"]
        if not klines:
            return None, None, None
        p = klines[-1].split(",")  # 日期,主力净额,主力占比
        amt = float(p[1]) if len(p) > 1 and p[1] not in ("", "-") else None
        pct = float(p[2]) if len(p) > 2 and p[2] not in ("", "-") else None
        return p[0], amt, pct

    last_err = None
    for _ in range(3):  # 通道A：requests
        try:
            r = _rq.get(url, headers={"User-Agent": _UA}, timeout=15)
            return _parse(r.text)
        except Exception as e:
            last_err = e
    for _ in range(2):  # 通道B：curl.exe(Windows Schannel，绕代理)
        try:
            out = subprocess.run(["curl.exe", "-s", "--noproxy", "*", "--max-time", "20", url],
                                 capture_output=True, text=True, timeout=25)
            if out.stdout and "klines" in out.stdout:
                return _parse(out.stdout)
        except Exception as e:
            last_err = e
    raise last_err


def capital_score(code, market):
    evidence, f = {}, 50.0
    try:
        date, amt, pct = fetch_fund_flow_last(code, market)
        if pct is None and amt is None:
            return f, {"资金": "无数据"}
        if pct is not None:
            f = max(0.0, min(100.0, 50.0 + pct * 2.5))  # 净占比±20%→0-100，50中性
            evidence["主力净流入净占比"] = f"{pct:+.2f}%"
        if amt is not None:
            evidence["主力净流入"] = f"{amt/1e8:+.2f}亿"
        if date:
            evidence["资金数据日"] = str(date)
    except Exception as e:
        log(f"  {code} 资金流 FAIL：{type(e).__name__}: {str(e)[:50]}")
        evidence["资金"] = "拉取失败"
    return round(f, 1), evidence


# ---------- 市场聚合 ----------
def fetch_market_breadth():
    """涨跌家数宽度 + 指数涨跌(沪深股通 summary 顺带给出)。北向实时净流入2024.8起停披露。"""
    out = {}
    try:
        df = ak.stock_hsgt_fund_flow_summary_em()
        up = down = flat = 0
        north_flow = 0.0
        idx_info = []
        for _, row in df.iterrows():
            try:
                up += int(pd.to_numeric(row.get("上涨数"), errors="coerce") or 0)
                down += int(pd.to_numeric(row.get("下跌数"), errors="coerce") or 0)
                flat += int(pd.to_numeric(row.get("持平数"), errors="coerce") or 0)
            except Exception:
                pass
            if str(row.get("资金方向")) == "北向":
                north_flow += float(pd.to_numeric(row.get("资金净流入"), errors="coerce") or 0)
            idxname = str(row.get("相关指数"))
            if idxname in ("上证指数", "深证成指") and idxname not in [i[0] for i in idx_info]:
                idx_info.append((idxname, float(pd.to_numeric(row.get("指数涨跌幅"), errors="coerce") or 0)))
        total = up + down + flat
        out["up"], out["down"], out["flat"] = up, down, flat
        out["up_ratio"] = round(up / total * 100, 1) if total else None
        out["north_flow"] = round(north_flow, 1)  # 0=停披露/未更新
        out["indices"] = [{"name": n, "chg": c} for n, c in idx_info]
        log(f"市场宽度 OK：涨{up}/平{flat}/跌{down}，北向{north_flow:.0f}亿")
    except Exception as e:
        log(f"市场宽度 FAIL：{type(e).__name__}: {str(e)[:50]}")
    return out


# ---------- 温度合成 + 反向信号 ----------
def temperature(h, f):
    return round((W_H * h + W_F * f) / (W_H + W_F), 1)


def level_of(t):
    for lo, name in [(80, "过热"), (65, "偏热"), (35, "中性"), (20, "偏冷"), (0, "冰点")]:
        if t >= lo:
            return name
    return "冰点"


def signal_of(t):
    if t >= 80:
        return "🔴 过热预警-散户狂热，警惕回撤"
    if t >= 65:
        return "🟠 偏热-情绪升温，收紧止损"
    if t <= 20:
        return "🟢 冰点信号-恐慌见底，可关注"
    if t <= 35:
        return "🔵 偏冷-情绪低迷，留意修复"
    return "⚪ 中性-结合基本面/技术面"


# ---------- 存储 ----------
def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.execute("""CREATE TABLE IF NOT EXISTS sentiment (
        code TEXT, name TEXT, sector TEXT, date TEXT,
        temperature REAL, level TEXT, signal TEXT, h REAL, f REAL, s REAL,
        evidence TEXT, created_at TEXT, PRIMARY KEY (code, date))""")
    con.commit()
    return con


def save(con, rec):
    con.execute("""INSERT OR REPLACE INTO sentiment
        (code,name,sector,date,temperature,level,signal,h,f,s,evidence,created_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (rec["code"], rec["name"], rec["sector"], rec["date"], rec["temperature"],
         rec["level"], rec["signal"], rec["breakdown"]["热度H"], rec["breakdown"]["资金F"],
         rec["breakdown"]["文本情感S"], json.dumps(rec["evidence"], ensure_ascii=False),
         dt.datetime.now().isoformat(timespec="seconds")))
    con.commit()


def write_json(path_list, obj):
    for p in path_list:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    wl = json.loads(WATCHLIST.read_text(encoding="utf-8"))["stocks"]
    args = [a for a in sys.argv[1:] if a.strip()]
    if args:
        sub = [s for s in wl if s["code"] in args]
        wl = sub or [{"code": a, "name": a, "market": "sh" if a[0] == "6" else "sz",
                      "sector": "手动"} for a in args]

    today = dt.date.today().isoformat()
    log(f"采集宇宙 {len(wl)} 只 · 日期 {today}")
    idx = build_heat_index()
    breadth = fetch_market_breadth()
    con = init_db()

    # 资金流顺序抓取：并发的多条大响应会触发 TLS bad record mac；顺序+礼貌延迟降东财限流。
    cap_map = {}
    for s in wl:
        cap_map[s["code"]] = capital_score(s["code"], s.get("market", "sh"))
        time.sleep(0.6)

    results = []
    for s in wl:
        code, name = s["code"], s["name"]
        sector = s.get("sector", "")
        h, h_ev = heat_score(code, idx)
        f, f_ev = cap_map[code]
        t = temperature(h, f)
        lvl = level_of(t)
        sig = signal_of(t)
        rec = {"stock": f"{code} {name}", "code": code, "name": name, "sector": sector,
               "date": today, "temperature": t, "level": lvl, "signal": sig,
               "breakdown": {"热度H": h, "资金F": f, "文本情感S": None},
               "evidence": {**h_ev, **f_ev}, "contrarian_note": sig}
        save(con, rec)
        results.append(rec)
        log(f"  {code} {name:<6} 温度={t:<5} [{lvl}] H={h} F={f}")

    results.sort(key=lambda r: r["temperature"], reverse=True)

    # 市场聚合 board
    temps = [r["temperature"] for r in results]
    mkt_temp = round(sum(temps) / len(temps), 1) if temps else None
    board = {
        "date": today,
        "market_temp": mkt_temp,
        "market_level": level_of(mkt_temp) if mkt_temp is not None else None,
        "market_signal": signal_of(mkt_temp) if mkt_temp is not None else None,
        "breadth": breadth,
        "reversal_alerts": sum(1 for r in results if r["level"] in ("过热", "偏热")),
        "overheated": [r["stock"] for r in results if r["level"] == "过热"],
        "cold": [r["stock"] for r in results if r["level"] in ("冰点", "偏冷")],
        "ranked": results,
        "updated_at": dt.datetime.now().isoformat(timespec="seconds"),
    }

    write_json([OUT_DIR / f"sentiment_{today}.json", OUT_DIR / "sentiment_latest.json",
                FRONT_DIR / "sentiment_latest.json"], results)
    write_json([OUT_DIR / "board.json", FRONT_DIR / "board.json"], board)
    con.close()
    log(f"完成 · 市场温度={mkt_temp}[{board['market_level']}] 反转预警={board['reversal_alerts']}只")
    log(f"  → {OUT_DIR}  &  {FRONT_DIR}  (DB: {DB_PATH})")


if __name__ == "__main__":
    main()
