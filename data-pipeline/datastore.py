# -*- coding: utf-8 -*-
"""
P2-B · 增量行情库 (Incremental Market Data Store)
═══════════════════════════════════════════════════════════════════════════════
根治「每天把 3 年历史重新下载一遍 + 数据源偶发挂死」的工业级数据底座。
零额外依赖:用 Python 内置 SQLite(本项目 collect.py 已在用),不需要 pyarrow/duckdb。

核心能力:
  ① 持久化:OHLCV 落 SQLite(data/market.db),主键(code,date),建索引,可增量。
  ② 增量更新:只补「上次入库日 → 今天」缺的那几根,而非全量重下 → 800 只回测从 20 分钟降到秒级。
  ③ 前复权漂移检测:前复权(qfq)价会因分红/送股「整段历史重算」。每次更新带一小段重叠区,
     若重叠区与库内值偏离 >0.5%(发生过除权)→ 自动对该股全量刷新替换,保证历史口径一致。
  ④ 多源失败转移:新浪(主) → 腾讯(备),任一通即可,绕开单点挂死。
  ⑤ 缓存迁移:一键把已有的当日 pkl 缓存(fib_scan 产出)导入库,不浪费已下载的数据。

对外:
  get_hist(code, days, update=True) → 前复权日线 DataFrame(open/high/low/close/vol),自动增量补齐。
  update_many(codes)               → 批量增量更新,返回 {成功, 失败}。
  migrate_from_cache()             → 把 data/cache/*.pkl 导入库。
  stats()                          → 库内股票数/总行数/日期范围。

用法:
  python datastore.py migrate      # 把现有 pkl 缓存导入库
  python datastore.py update 600519 300308   # 增量更新指定股
  python datastore.py stats        # 看库存
  python datastore.py test 600519  # 取一只验证
"""
import os
import sys
import sqlite3
import time
import pickle
import datetime as dt
from pathlib import Path

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

BASE = Path(__file__).resolve().parent
DB_PATH = BASE / "data" / "market.db"
CACHE_DIR = BASE / "data" / "cache"
DEFAULT_DAYS = 1100
DRIFT_TOL = 0.005          # 前复权重叠区偏离 >0.5% 判为除权 → 全量刷新
OVERLAP = 6                # 增量时回带的重叠根数(用于漂移检测)


def log(m):
    print(f"[{dt.datetime.now():%H:%M:%S}] {m}", flush=True)


# ───────────────────────── DB ─────────────────────────
def _con():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.execute("""CREATE TABLE IF NOT EXISTS prices(
        code TEXT, date TEXT, open REAL, high REAL, low REAL, close REAL, vol REAL,
        PRIMARY KEY(code, date))""")
    con.execute("CREATE INDEX IF NOT EXISTS idx_code_date ON prices(code, date)")
    con.execute("""CREATE TABLE IF NOT EXISTS meta(
        code TEXT PRIMARY KEY, last_update TEXT, rows INTEGER, source TEXT)""")
    con.commit()
    return con


def _read_local(con, code) -> pd.DataFrame:
    df = pd.read_sql_query(
        "SELECT date,open,high,low,close,vol FROM prices WHERE code=? ORDER BY date",
        con, params=(code,))
    if df.empty:
        return df
    df["date"] = pd.to_datetime(df["date"])
    return df.set_index("date")


def _last_date(con, code):
    r = con.execute("SELECT MAX(date) FROM prices WHERE code=?", (code,)).fetchone()
    return r[0] if r and r[0] else None


def _upsert(con, code, df, source="sina"):
    rows = [(code, d.strftime("%Y-%m-%d"),
             _f(r.get("open")), _f(r.get("high")), _f(r.get("low")), _f(r.get("close")), _f(r.get("vol")))
            for d, r in df.iterrows()]
    con.executemany("""INSERT OR REPLACE INTO prices(code,date,open,high,low,close,vol)
        VALUES(?,?,?,?,?,?,?)""", rows)
    n = con.execute("SELECT COUNT(*) FROM prices WHERE code=?", (code,)).fetchone()[0]
    con.execute("INSERT OR REPLACE INTO meta(code,last_update,rows,source) VALUES(?,?,?,?)",
                (code, dt.datetime.now().isoformat(timespec="seconds"), n, source))
    con.commit()


def _f(x):
    try:
        v = float(x)
        return v if np.isfinite(v) else None
    except Exception:
        return None


# ───────────────────────── 取价(多源失败转移) ─────────────────────────
def _sina_symbol(code):
    c = str(code)
    if c.startswith("6"):
        return "sh" + c
    if c.startswith(("4", "8")):
        return "bj" + c
    return "sz" + c


def _fetch_sina(code, start, end):
    df = ak.stock_zh_a_daily(symbol=_sina_symbol(code), adjust="qfq",
                             start_date=start, end_date=end)
    if df is None or df.empty:
        raise ValueError("空数据")
    df = df.rename(columns={"volume": "vol"})
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date").sort_index()
    cols = [c for c in ["open", "high", "low", "close", "vol"] if c in df.columns]
    return df[cols].apply(pd.to_numeric, errors="coerce").dropna(subset=["close"]), "sina"


def _fetch_tx(code, start, end):
    """腾讯源兜底(host 与新浪/东财都不同,单点挂死时救命)。"""
    df = ak.stock_zh_a_hist_tx(symbol=_sina_symbol(code), start_date=start, end_date=end, adjust="qfq")
    if df is None or df.empty:
        raise ValueError("空数据")
    df = df.rename(columns={"date": "date", "amount": "vol"})
    # tx 列名:date open close high low amount
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date").sort_index()
    cols = [c for c in ["open", "high", "low", "close", "vol"] if c in df.columns]
    return df[cols].apply(pd.to_numeric, errors="coerce").dropna(subset=["close"]), "tencent"


def _fetch(code, start, end):
    """多源失败转移:新浪(主,3 试) → 腾讯(备,2 试)。全失败抛异常。"""
    last_err = None
    for _ in range(3):
        try:
            return _fetch_sina(code, start, end)
        except Exception as e:
            last_err = e
            time.sleep(0.5)
    for _ in range(2):
        try:
            return _fetch_tx(code, start, end)
        except Exception as e:
            last_err = e
            time.sleep(0.5)
    raise last_err


# ───────────────────────── 对外:增量取价 ─────────────────────────
def get_hist(code, days=DEFAULT_DAYS, update=True, con=None) -> pd.DataFrame:
    """前复权日线(open/high/low/close/vol),自动增量补齐。失败抛异常。"""
    own = con is None
    if own:
        con = _con()
    try:
        local = _read_local(con, code)
        today = dt.date.today()
        last = _last_date(con, code)
        if update:
            if last is None:                       # 库内无 → 全量首取
                start = (today - dt.timedelta(days=days + 30)).strftime("%Y%m%d")
                new, src = _fetch(code, start, today.strftime("%Y%m%d"))
                _upsert(con, code, new, src)
                local = _read_local(con, code)
            elif last < today.isoformat():         # 有缺口 → 增量(带重叠区做漂移检测)
                ov_start = (pd.Timestamp(last) - pd.Timedelta(days=OVERLAP * 2)).strftime("%Y%m%d")
                new, src = _fetch(code, ov_start, today.strftime("%Y%m%d"))
                if _qfq_drifted(local, new):       # 除权导致历史重算 → 全量刷新替换
                    log(f"  {code} 检测到前复权漂移(除权),全量刷新")
                    con.execute("DELETE FROM prices WHERE code=?", (code,))
                    start = (today - dt.timedelta(days=days + 30)).strftime("%Y%m%d")
                    full, src = _fetch(code, start, today.strftime("%Y%m%d"))
                    _upsert(con, code, full, src)
                else:
                    _upsert(con, code, new, src)
                local = _read_local(con, code)
        if local.empty:
            raise ValueError("无数据")
        return local.iloc[-days:] if len(local) > days else local
    finally:
        if own:
            con.close()


def _qfq_drifted(local: pd.DataFrame, new: pd.DataFrame) -> bool:
    """重叠日期上,库内 close 与新取 close 偏离 >容差 → 发生过除权,需全量刷新。"""
    if local.empty or new.empty:
        return False
    common = local.index.intersection(new.index)
    if len(common) == 0:
        return False
    a = local.loc[common, "close"].to_numpy(dtype=float)
    b = new.loc[common, "close"].to_numpy(dtype=float)
    with np.errstate(invalid="ignore", divide="ignore"):
        rel = np.abs(a - b) / np.where(b != 0, np.abs(b), np.nan)
    return bool(np.nanmax(rel) > DRIFT_TOL) if rel.size else False


def update_many(codes, sleep=0.12):
    con = _con()
    ok, fail = [], []
    try:
        for i, code in enumerate(codes):
            try:
                get_hist(code, update=True, con=con)
                ok.append(code)
            except Exception as e:
                fail.append(code)
                log(f"  [{i+1}/{len(codes)}] {code} 更新失败:{type(e).__name__}: {str(e)[:34]}")
            time.sleep(sleep)
    finally:
        con.close()
    return {"ok": ok, "fail": fail}


# ───────────────────────── 缓存迁移 / 统计 ─────────────────────────
def migrate_from_cache():
    """把 data/cache/*.pkl(fib_scan 当日缓存)导入库,不浪费已下载数据。"""
    con = _con()
    n = 0
    try:
        for pf in sorted(CACHE_DIR.glob("*.pkl")):
            code = pf.stem.split("_")[0]
            try:
                df = pickle.loads(pf.read_bytes())
                if isinstance(df, pd.DataFrame) and not df.empty:
                    _upsert(con, code, df, "cache")
                    n += 1
            except Exception as e:
                log(f"  {pf.name} 导入失败:{type(e).__name__}")
    finally:
        con.close()
    log(f"缓存迁移完成:导入 {n} 只")
    return n


def stats():
    con = _con()
    try:
        nc = con.execute("SELECT COUNT(DISTINCT code) FROM prices").fetchone()[0]
        nr = con.execute("SELECT COUNT(*) FROM prices").fetchone()[0]
        rng = con.execute("SELECT MIN(date),MAX(date) FROM prices").fetchone()
        sz = DB_PATH.stat().st_size / 1e6 if DB_PATH.exists() else 0
        return {"stocks": nc, "rows": nr, "date_range": f"{rng[0]}→{rng[1]}" if rng[0] else "空",
                "db_mb": round(sz, 1)}
    finally:
        con.close()


def main():
    args = sys.argv[1:]
    cmd = args[0] if args else "stats"
    if cmd == "migrate":
        migrate_from_cache()
        log(f"库存:{stats()}")
    elif cmd == "update":
        codes = args[1:] or []
        if not codes:
            log("用法:python datastore.py update <code...>")
            return
        t0 = time.time()
        r = update_many(codes)
        log(f"增量更新 {len(r['ok'])} 成功 / {len(r['fail'])} 失败 · 用时 {time.time()-t0:.1f}s")
    elif cmd == "update-watchlist":
        # 盘前定时任务用:增量更新 watchlist(或 SENTIO_WATCHLIST 指定宇宙)全部代码
        import json as _json
        wl_name = os.environ.get("SENTIO_WATCHLIST", "watchlist.json")
        codes = [s["code"] for s in _json.loads((BASE / wl_name).read_text(encoding="utf-8"))["stocks"]]
        t0 = time.time()
        r = update_many(codes)
        log(f"增量更新 {wl_name}：{len(r['ok'])} 成功 / {len(r['fail'])} 失败 · 用时 {time.time()-t0:.1f}s")
    elif cmd == "test":
        code = args[1] if len(args) > 1 else "600519"
        t0 = time.time()
        df = get_hist(code)
        log(f"{code}: {len(df)} 根 {df.index[0].date()}→{df.index[-1].date()} · 用时 {time.time()-t0:.2f}s")
        print(df.tail(3))
    else:
        log(f"库存:{stats()}")


if __name__ == "__main__":
    main()
