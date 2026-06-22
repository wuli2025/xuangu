# -*- coding: utf-8 -*-
"""
P4 · AI 催化剂否决层 (AI Catalyst / Red-Flag Veto)
═══════════════════════════════════════════════════════════════════════════════
量化的最后一道关:技术面选出的候选股,用「真实新闻/公告」过一遍风险否决。
设计铁律——**防幻觉**:AI 只基于「我们喂给它的真实新闻」做判断,绝不凭训练记忆/凭空推荐。
而且 AI 只做「否决与加权」,不新增选股(职责边界:技术面负责进攻,AI 负责排雷)。

两层(确定性兜底 + 可选 AI 深研):
  ① 关键词红旗扫描(确定性、离线、零成本)：对每只候选拉近期新闻,扫描
       减持/问询函/立案/调查/退市/商誉减值/业绩预亏/诉讼/违规处罚/质押爆仓/实控人变动… → 风险分。
       命中硬红旗(立案/退市/问询函/财务造假)直接 veto。
  ② LLM 深度研判(可选,SENTIO_AI_LLM=1 启用)：把新闻喂给 claude CLI,让它在「仅依据所给新闻」
       的约束下，给出 veto/keep + 催化剂分 + 理由(JSON)。CLI 不可用/超时则自动退回第①层。

产出 output/ai_veto.json(+前端):每只 {veto, risk_score, red_flags, catalyst, verdict, source}。
被 veto 的候选,前端可标红/降级;实盘/纸上交易据此过滤。

用法：
  python ai_veto.py                 # 对 fib_strategy.json 的 fresh_entry 候选排雷(关键词层)
  $env:SENTIO_AI_LLM=1; python ai_veto.py   # 叠加 claude CLI 深度研判
  python ai_veto.py 600519 300308   # 指定代码
"""
import os
import sys
import json
import subprocess
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

import akshare as ak

BASE = Path(__file__).resolve().parent
OUT_DIR = BASE / "output"
FRONT_DIR = BASE.parent / "polaris-app" / "public" / "sentio"
STRATEGY_JSON = OUT_DIR / "fib_strategy.json"
CLAUDE_CLI = os.environ.get("CLAUDE_CLI", r"C:\Users\mi\.local\bin\claude.cmd")
USE_LLM = os.environ.get("SENTIO_AI_LLM", "") in ("1", "true", "on")
MAX_LLM = int(os.environ.get("SENTIO_AI_MAX", "5"))   # LLM 最多研判几只(控成本)

# ── 红旗词(命中即高风险/否决)与软风险词、催化剂词 ──
HARD_FLAGS = ["立案", "退市", "暂停上市", "财务造假", "问询函", "关注函", "处罚", "违规", "涉嫌"]
SOFT_FLAGS = ["减持", "商誉", "预亏", "亏损", "诉讼", "仲裁", "冻结", "质押", "辞职", "下修", "业绩变脸", "解禁"]
CATALYSTS = ["中标", "订单", "预增", "回购", "增持", "合作", "突破", "涨价", "获批", "签约", "扭亏", "新高"]


def log(m):
    print(f"[{dt.datetime.now():%H:%M:%S}] {m}", flush=True)


def fetch_news(code, limit=10):
    """近期新闻标题+内容片段。失败返回 []。"""
    try:
        df = ak.stock_news_em(symbol=code)
        if df is None or df.empty:
            return []
        tcol = next((c for c in df.columns if "标题" in str(c)), df.columns[1])
        ccol = next((c for c in df.columns if "内容" in str(c)), None)
        dcol = next((c for c in df.columns if "时间" in str(c)), None)
        out = []
        for _, r in df.head(limit).iterrows():
            out.append({"title": str(r[tcol]),
                        "summary": (str(r[ccol])[:80] if ccol else ""),
                        "time": (str(r[dcol]) if dcol else "")})
        return out
    except Exception as e:
        log(f"  {code} 新闻拉取失败:{type(e).__name__}: {str(e)[:36]}")
        return []


def keyword_scan(news):
    """确定性红旗扫描 → (risk_score 0-100, red_flags[], catalysts[])。"""
    text = " ".join((n["title"] + " " + n["summary"]) for n in news)
    hard = sorted({w for w in HARD_FLAGS if w in text})
    soft = sorted({w for w in SOFT_FLAGS if w in text})
    cata = sorted({w for w in CATALYSTS if w in text})
    risk = min(100, len(hard) * 35 + len(soft) * 12)
    return risk, hard + soft, cata


def llm_judge(code, name, news):
    """可选:claude CLI 基于所给新闻做研判,返回 dict 或 None(失败/超时)。"""
    if not news:
        return None
    lines = "\n".join(f"- [{n['time']}] {n['title']} {n['summary']}" for n in news)
    prompt = (
        f"你是A股风险排雷分析师。只能依据下面这只股票({code} {name})的真实新闻判断,"
        f"严禁使用新闻之外的任何记忆或猜测。识别是否存在重大利空红旗"
        f"(减持/问询函/立案调查/商誉爆雷/业绩暴雷/退市风险/重大诉讼/实控人风险)。\n\n"
        f"新闻:\n{lines}\n\n"
        f"只输出一行 JSON(不要解释、不要代码块):"
        f'{{"veto": true/false, "catalyst_score": 0-100, "red_flags": ["..."], "reason": "一句话"}}'
        f"。veto=true 仅当新闻里有明确重大利空;没有就 false。"
    )
    try:
        r = subprocess.run([CLAUDE_CLI, "-p"], input=prompt, capture_output=True,
                           text=True, encoding="utf-8", timeout=90)
        out = (r.stdout or "").strip()
        s, e = out.find("{"), out.rfind("}")
        if s >= 0 and e > s:
            return json.loads(out[s:e + 1])
    except Exception as ex:
        log(f"  {code} LLM 研判失败({type(ex).__name__}),退回关键词层")
    return None


def assess(code, name):
    news = fetch_news(code)
    risk, flags, cata = keyword_scan(news)
    veto = any(w in flags for w in HARD_FLAGS) or risk >= 60
    source = "keyword"
    reason = ("命中硬红旗:" + "、".join([w for w in flags if w in HARD_FLAGS])) if veto else \
             (("软风险:" + "、".join(flags)) if flags else "近期新闻无明显红旗")
    catalyst_score = min(100, len(cata) * 25)

    if USE_LLM and news:
        j = llm_judge(code, name, news)
        if j is not None:
            source = "llm"
            veto = bool(j.get("veto", veto))
            catalyst_score = int(j.get("catalyst_score", catalyst_score))
            if j.get("red_flags"):
                flags = sorted(set(flags) | set(j["red_flags"]))
            reason = j.get("reason", reason)

    return {
        "code": code, "name": name,
        "veto": veto,
        "risk_score": risk,
        "catalyst_score": catalyst_score,
        "red_flags": flags,
        "catalysts": cata,
        "verdict": ("🔴 否决·疑似利空" if veto else
                    ("🟡 注意·有软风险" if flags else "🟢 通过·无明显红旗")),
        "reason": reason,
        "news_count": len(news),
        "source": source,
    }


def main():
    args = [a for a in sys.argv[1:] if a.strip()]
    if args:
        targets = [{"code": a, "name": a} for a in args]
    else:
        strat = json.loads(STRATEGY_JSON.read_text(encoding="utf-8")) if STRATEGY_JSON.exists() else {}
        # 评估所有今日候选(新进场+持有+待进),让前端每张卡都有 AI 排雷徽章;上限控网络成本
        cap = int(os.environ.get("SENTIO_AI_CAP", "24"))
        cands = strat.get("candidates", [])[:cap]
        targets = [{"code": c["code"], "name": c.get("name", c["code"])} for c in cands]
    if not targets:
        log("无候选可排雷(先跑 fib_scan)")
        return

    mode = "关键词 + LLM深研" if USE_LLM else "关键词红旗扫描"
    log(f"AI 催化剂否决层 · {len(targets)} 只候选 · 模式:{mode}")
    results = []
    llm_used = 0
    for i, t in enumerate(targets):
        use_llm_this = USE_LLM and llm_used < MAX_LLM
        if USE_LLM and not use_llm_this:
            os.environ["SENTIO_AI_LLM"] = ""   # 超出预算的退回关键词
        r = assess(t["code"], t["name"])
        if r["source"] == "llm":
            llm_used += 1
        results.append(r)
        log(f"  [{i+1}/{len(targets)}] {t['code']} {t['name']:<8} {r['verdict']} "
            f"风险{r['risk_score']} 催化{r['catalyst_score']} [{r['source']}] {r['reason'][:30]}")
    if USE_LLM:
        os.environ["SENTIO_AI_LLM"] = "1"

    vetoed = [r["code"] for r in results if r["veto"]]
    out = {
        "date": dt.date.today().isoformat(),
        "mode": mode,
        "assessed": len(results),
        "vetoed": vetoed,
        "veto_count": len(vetoed),
        "keep": [r["code"] for r in results if not r["veto"]],
        "results": results,
        "note": "AI 仅基于真实新闻做否决/加权排雷,不凭空选股(防幻觉)。研究参考,非投资建议。",
        "updated_at": dt.datetime.now().isoformat(timespec="seconds"),
    }
    for p in (OUT_DIR / "ai_veto.json", FRONT_DIR / "ai_veto.json"):
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"完成 · 否决 {len(vetoed)} / {len(results)} 只 · → {OUT_DIR/'ai_veto.json'}(+前端)")


if __name__ == "__main__":
    main()
