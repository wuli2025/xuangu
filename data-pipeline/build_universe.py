# -*- coding: utf-8 -*-
"""
P2-A · 全市场宇宙构造器 (Universe Builder)
═══════════════════════════════════════════════════════════════════════════════
把策略宇宙从「32 只手选龙头」扩到「指数成分可投资域」——这是收益天花板第一因:
手选龙头有幸存者偏差(事后才知道谁是龙头) + 趋势信号供给不足(32 只里同期能金叉的极少)。
扩大可投资域让非对称大赢家的命中数量级提升。

为什么用指数成分而非「全市场按成交额排序」:
  • 沪深300 + 中证500(=中证800)是规则化、天然流动、定期再平衡的标准机构可投资域,
    成分由指数公司按市值/流动性纳入——这本身就是一道客观流动性闸,且无「手选幸存者偏差」。
  • 成分接口是小响应,绕开东财全市场快照的大响应 TLS 墙(stock_zh_a_spot_em 实测被本机网络
    路径 RemoteDisconnected 打断,见踩坑)。
  • 再叠一道 ST/退市剔除兜底。

数据源:中证官方成分 index_stock_cons_csindex(000300/000905);
       兜底 新浪 index_stock_cons → stock_info_a_code_name。

产出 universe.json。用 SENTIO_WATCHLIST=universe.json 让 fib_scan/strategy 跑这个大宇宙。
用法:python build_universe.py [TOP_N]    # TOP_N 可选,截断到前 N 只(0/省略=全量中证800)
"""
import os
import sys
import json
import socket
import datetime as dt
from pathlib import Path

# akshare 的成分/快照接口无超时,本机网络偶发挂死(中证500 csindex 实测卡 3 分钟+)。
# 设全局 socket 超时 → 挂起变成可捕获异常,触发兜底而非永久阻塞。
socket.setdefaulttimeout(25)

for _k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
    os.environ.pop(_k, None)
import requests as _rq
_orig = _rq.sessions.Session.__init__


def _no_proxy(self, *a, **k):
    _orig(self, *a, **k)
    self.trust_env = False
    self.proxies = {}


_rq.sessions.Session.__init__ = _no_proxy

import pandas as pd
import akshare as ak

BASE = Path(__file__).resolve().parent
OUT = BASE / "universe.json"

INDEX_MEMBERS = ["000300", "000905"]   # 沪深300 + 中证500 = 中证800 标准可投资域
TOP_N_DEFAULT = 0        # 0=全量(中证800≈800只);>0 截断到前 N(按指数顺序)


def log(m):
    print(f"[{dt.datetime.now():%H:%M:%S}] {m}", flush=True)


def find_col(df, *keys):
    for k in keys:
        for c in df.columns:
            if k in str(c):
                return c
    return None


def market_of(code):
    c = str(code)
    if c.startswith("6"):
        return "sh"
    if c.startswith(("4", "8")):
        return "bj"
    return "sz"


def _fetch_cons(idx):
    """取单个指数成分 (code,name) 列表。中证官方接口为主,新浪兜底。"""
    try:
        df = ak.index_stock_cons_csindex(symbol=idx)
        ccol = find_col(df, "成分券代码", "代码")
        ncol = find_col(df, "成分券名称", "名称")
        if ccol and ncol:
            return [(str(r[ccol]).zfill(6), str(r[ncol])) for _, r in df.iterrows()]
    except Exception as e:
        log(f"  {idx} 中证官方成分失败:{type(e).__name__}: {str(e)[:40]} → 试新浪")
    df = ak.index_stock_cons(symbol=idx)   # 新浪兜底
    ccol = find_col(df, "品种代码", "代码", "code")
    ncol = find_col(df, "品种名称", "名称", "name")
    return [(str(r[ccol]).zfill(6), str(r[ncol])) for _, r in df.iterrows()]


def build(top_n=TOP_N_DEFAULT):
    seen, pairs = set(), []
    for idx in INDEX_MEMBERS:
        log(f"取指数成分 {idx}…")
        try:
            cons = _fetch_cons(idx)
        except Exception as e:
            log(f"  {idx} 取成分失败(跳过,不阻断并集):{type(e).__name__}: {str(e)[:40]}")
            continue
        log(f"  {idx}: {len(cons)} 只")
        for code, name in cons:
            if code not in seen:
                seen.add(code)
                pairs.append((code, name))
    if not pairs:
        raise RuntimeError("所有指数成分均获取失败")
    # ST/退市兜底剔除
    out = []
    for code, name in pairs:
        if "ST" in name.upper() or "退" in name:
            continue
        out.append({"code": code, "name": name.replace(" ", ""),
                    "market": market_of(code), "sector": ""})
    log(f"  并集去重 {len(pairs)} → 剔ST/退市后 {len(out)} 只")
    if top_n and len(out) > top_n:
        out = out[:top_n]
        log(f"  截断到前 {top_n}")
    return out


def build_fallback():
    log("快照失败,兜底 stock_info_a_code_name(仅 code+name,保留非 ST 全量)…")
    df = ak.stock_info_a_code_name()
    ccol = find_col(df, "code", "代码")
    ncol = find_col(df, "name", "名称")
    out = []
    for _, r in df.iterrows():
        code = str(r[ccol]).zfill(6)[-6:]
        name = str(r[ncol])
        if "ST" in name.upper() or "退" in name:
            continue
        out.append({"code": code, "name": name, "market": market_of(code), "sector": ""})
    return out


def main():
    top_n = TOP_N_DEFAULT
    if len(sys.argv) > 1 and sys.argv[1].isdigit():
        top_n = int(sys.argv[1])
    try:
        stocks = build(top_n)
    except Exception as e:
        log(f"快照失败:{type(e).__name__}: {str(e)[:60]}")
        try:
            stocks = build_fallback()
            if top_n:
                stocks = stocks[:top_n]
        except Exception as e2:
            log(f"兜底也失败:{type(e2).__name__}: {e2}")
            return

    obj = {
        "_comment": f"指数成分可投资域(build_universe.py,{dt.date.today().isoformat()})。"
                    f"沪深300+中证500并集、剔ST/退市{('、截断TOP'+str(top_n)) if top_n else '(全量)'}。"
                    f"用 SENTIO_WATCHLIST=universe.json 启用。",
        "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "count": len(stocks),
        "source": {"indexes": INDEX_MEMBERS, "top_n": top_n},
        "stocks": stocks,
    }
    OUT.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"完成 · {len(stocks)} 只 → {OUT}")
    # 行业分布速览
    from collections import Counter
    secs = Counter(s["sector"] for s in stocks if s["sector"])
    if secs:
        top = "、".join(f"{k}{v}" for k, v in secs.most_common(8))
        log(f"  行业分布 Top8:{top}")
    log(f"  示例:{[s['code']+' '+s['name'] for s in stocks[:5]]}")


if __name__ == "__main__":
    main()
