# -*- coding: utf-8 -*-
"""读 board.json，按 SENTIO PRD 深空玻璃风格生成 HTML 报告到桌面。
用法：python gen_report.py [输出路径]"""
import sys
import json
import datetime as dt
from pathlib import Path

BASE = Path(__file__).resolve().parent
BOARD = BASE / "output" / "board.json"
DESKTOP = Path.home() / "Desktop"
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else DESKTOP / "SENTIO舆情采集报告.html"

LEVEL_COLOR = {"过热": "#ff5470", "偏热": "#ffcf6b", "中性": "#8a93a8",
               "偏冷": "#5b8cff", "冰点": "#00e69a"}


def temp_color(t):
    if t >= 80:
        return "#ff5470"
    if t >= 65:
        return "#ffcf6b"
    if t <= 20:
        return "#00e69a"
    if t <= 35:
        return "#5b8cff"
    return "#8a93a8"


def rec_card(r, top=False):
    t = r["temperature"]
    c = temp_color(t)
    bd = r["breakdown"]
    ev = r["evidence"]
    ev_rows = "".join(
        f'<div class="ev"><span class="ek">{k}</span><span class="evv">{v}</span></div>'
        for k, v in ev.items())
    pct = max(0, min(100, t))
    return f"""
    <div class="rec {'top' if top else ''}">
      <div class="ringbox">
        <div class="ring" style="background:conic-gradient({c} 0 {pct}%,rgba(255,255,255,.08) {pct}% 100%)">
          <div class="rnum" style="color:{c}">{t:.0f}</div>
        </div>
        <div class="rlvl" style="color:{c}">{r['level']}</div>
      </div>
      <div class="rmid">
        <div class="rnm">{r['name']} <small>{r['code']} · {r['sector']}</small></div>
        <div class="rsig" style="color:{c}">{r['signal']}</div>
        <div class="bars">
          <div class="bar"><span class="bl">热度 H</span><span class="btrk"><i style="width:{bd['热度H']}%;background:linear-gradient(90deg,#5b8cff,#00e0c6)"></i></span><span class="bv">{bd['热度H']:.0f}</span></div>
          <div class="bar"><span class="bl">资金 F</span><span class="btrk"><i style="width:{bd['资金F']}%;background:linear-gradient(90deg,#00e69a,#33e0ff)"></i></span><span class="bv">{bd['资金F']:.0f}</span></div>
          <div class="bar"><span class="bl dim">情感 S</span><span class="btrk"></span><span class="bv dim">—</span></div>
        </div>
        <div class="evs">{ev_rows}</div>
      </div>
    </div>"""


def main():
    board = json.loads(BOARD.read_text(encoding="utf-8"))
    mt = board.get("market_temp") or 0
    bw = board.get("breadth", {})
    mc = temp_color(mt)
    ranked = board.get("ranked", [])
    indices = bw.get("indices", [])
    idx_html = " · ".join(
        f'{i["name"]} <b style="color:{"#00e69a" if i["chg"]>=0 else "#ff5470"}">{i["chg"]:+.2f}%</b>'
        for i in indices) or "—"
    up, down, flat = bw.get("up", 0), bw.get("down", 0), bw.get("flat", 0)
    up_ratio = bw.get("up_ratio") or 0
    cards = "".join(rec_card(r, top=(i == 0)) for i, r in enumerate(ranked))
    gen_time = dt.datetime.now().strftime("%Y-%m-%d %H:%M")

    html = f"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>SENTIO · 舆情采集报告 {board.get('date','')}</title>
<style>
:root{{--bg:#070a12;--bg2:#0c1019;--card:rgba(255,255,255,.045);--card2:rgba(255,255,255,.07);
--line:rgba(255,255,255,.09);--line2:rgba(255,255,255,.14);--txt:#f0f3fa;--sub:#8a93a8;--dim:#5c6378;
--up:#00e69a;--down:#ff5470;--gold:#ffcf6b;--grad:linear-gradient(120deg,#5b8cff,#00e0c6);
--grad-gold:linear-gradient(120deg,#ffcf6b,#ff9d5c);}}
*{{box-sizing:border-box;}}
body{{margin:0;font-family:-apple-system,BlinkMacSystemFont,"SF Pro SC","PingFang SC","Microsoft YaHei",sans-serif;
background:var(--bg);color:var(--txt);line-height:1.6;-webkit-font-smoothing:antialiased;letter-spacing:.01em;
background-image:radial-gradient(circle at 15% 5%,rgba(91,140,255,.12),transparent 40%),radial-gradient(circle at 85% 12%,rgba(0,224,198,.10),transparent 42%);background-attachment:fixed;}}
.wrap{{max-width:1000px;margin:0 auto;padding:46px 28px 90px;}}
.eyebrow{{font-size:13px;font-weight:600;letter-spacing:.06em;background:var(--grad);-webkit-background-clip:text;background-clip:text;color:transparent;}}
h1{{font-size:38px;font-weight:800;letter-spacing:-.02em;margin:10px 0 6px;}}
.sub{{color:var(--sub);font-size:15px;}}
.live{{display:inline-flex;align-items:center;gap:7px;font-size:12px;color:var(--up);margin-left:8px;}}
.live::before{{content:"";width:7px;height:7px;border-radius:50%;background:var(--up);box-shadow:0 0 8px var(--up);}}
.dash{{display:flex;gap:16px;flex-wrap:wrap;margin:30px 0 14px;}}
.gauge{{flex:1.4;min-width:240px;border:1px solid var(--line);border-radius:20px;padding:24px;background:var(--card);position:relative;overflow:hidden;}}
.gauge::after{{content:"";position:absolute;right:-30px;top:-30px;width:140px;height:140px;border-radius:50%;background:{mc};opacity:.16;filter:blur(26px);}}
.gauge .k{{font-size:12px;color:var(--sub);}}
.gauge .big{{font-size:62px;font-weight:800;letter-spacing:-.03em;line-height:1;margin:6px 0;color:{mc};}}
.gauge .tag{{font-size:13px;color:{mc};font-weight:700;}}
.stat{{flex:1;min-width:150px;border:1px solid var(--line);border-radius:20px;padding:20px;background:var(--card);}}
.stat .k{{font-size:12px;color:var(--sub);}}
.stat .v{{font-size:28px;font-weight:700;margin-top:6px;}}
.stat .s{{font-size:11px;color:var(--dim);margin-top:3px;}}
.up{{color:var(--up);}} .down{{color:var(--down);}}
.sechead{{font-size:13px;font-weight:700;letter-spacing:.05em;background:var(--grad);-webkit-background-clip:text;background-clip:text;color:transparent;margin:40px 0 4px;}}
h2{{font-size:24px;font-weight:800;margin:2px 0 18px;letter-spacing:-.02em;}}
.recs{{display:grid;gap:13px;}}
.rec{{display:flex;gap:20px;border:1px solid var(--line);border-radius:18px;padding:18px 20px;background:var(--card);}}
.rec.top{{border-color:rgba(255,207,107,.35);background:linear-gradient(100deg,rgba(255,207,107,.06),transparent 60%);}}
.ringbox{{flex-shrink:0;text-align:center;width:96px;}}
.ring{{width:84px;height:84px;border-radius:50%;margin:0 auto;display:flex;align-items:center;justify-content:center;position:relative;}}
.ring::before{{content:"";position:absolute;inset:9px;border-radius:50%;background:var(--bg2);}}
.rnum{{position:relative;font-size:26px;font-weight:800;}}
.rlvl{{font-size:12px;font-weight:700;margin-top:8px;}}
.rmid{{flex:1;min-width:0;}}
.rnm{{font-size:17px;font-weight:700;}}
.rnm small{{color:var(--dim);font-weight:400;font-size:12px;margin-left:7px;}}
.rsig{{font-size:13px;font-weight:600;margin:3px 0 12px;}}
.bars{{display:flex;flex-direction:column;gap:6px;max-width:440px;}}
.bar{{display:flex;align-items:center;gap:10px;font-size:12px;}}
.bar .bl{{width:42px;color:var(--sub);flex-shrink:0;}}
.bar .bl.dim{{color:var(--dim);}}
.btrk{{flex:1;height:6px;border-radius:980px;background:rgba(255,255,255,.06);overflow:hidden;}}
.btrk i{{display:block;height:100%;border-radius:980px;}}
.bar .bv{{width:24px;text-align:right;font-weight:700;font-family:"SF Mono",Consolas,monospace;}}
.bar .bv.dim{{color:var(--dim);}}
.evs{{display:flex;flex-wrap:wrap;gap:6px 16px;margin-top:13px;}}
.ev{{font-size:12px;}}
.ev .ek{{color:var(--dim);margin-right:6px;}}
.ev .evv{{color:var(--sub);font-weight:600;}}
.note{{border:1px solid var(--line);border-radius:16px;padding:18px 22px;margin:30px 0;background:var(--card);font-size:13.5px;color:var(--sub);}}
.note b{{color:var(--txt);}}
.note.warn{{box-shadow:inset 3px 0 0 var(--gold);}}
.note.key{{box-shadow:inset 3px 0 0 #00e0c6;}}
footer{{margin-top:50px;padding-top:24px;border-top:1px solid var(--line);color:var(--dim);font-size:12.5px;text-align:center;}}
</style></head>
<body><div class="wrap">
  <div class="eyebrow">SENTIO · AI 智能选股舆情终端</div>
  <h1>舆情采集报告</h1>
  <div class="sub">采集日期 {board.get('date','')} · 第①②层（热度 H + 资金 F）· 自选宇宙 {len(ranked)} 只<span class="live">数据已落库</span></div>

  <div class="dash">
    <div class="gauge">
      <div class="k">市场情绪温度（自选池均值）</div>
      <div class="big">{mt:.0f}</div>
      <div class="tag">{board.get('market_signal','')}</div>
    </div>
    <div class="stat"><div class="k">涨跌家数（沪深）</div><div class="v"><span class="up">{up}</span> / <span class="down">{down}</span></div><div class="s">上涨占比 {up_ratio:.0f}% · 平 {flat}</div></div>
    <div class="stat"><div class="k">情绪反转预警</div><div class="v down">{board.get('reversal_alerts',0)} 只</div><div class="s">过热/偏热 · 散户偏一致</div></div>
    <div class="stat"><div class="k">大盘指数</div><div class="v" style="font-size:15px;line-height:1.5;margin-top:10px;">{idx_html}</div></div>
  </div>

  <div class="sechead">RANKED · 按情绪温度排序</div>
  <h2>个股情绪温度榜</h2>
  <div class="recs">{cards}</div>

  <div class="note key"><b>怎么读这张表：</b>情绪是<b>反向指标</b>——温度≥80（过热）代表散户狂热、警惕回撤；≤20（冰点）代表恐慌见底、可关注。热度 H = 千股千评关注指数的全市场分位（+人气榜加成）；资金 F = 主力净流入净占比映射；情感 S（文本情感）为第二阶段接入项。本批自选多为大盘明星股，H 天然偏高，真正的反转信号需靠每日累积算<b>二阶动量（较5日均值飙升）</b>。</div>
  <div class="note warn"><b>本次采集说明：</b>资金 F 中标注「拉取失败」的标的因东财 push2his 接口盘中限流（本机调试期高频访问触发），已按中性值 50 计入；代码已加最小字段请求 + curl 兜底 + 礼貌延迟，限流缓解后重跑即恢复真实值。北向资金实时净流入自 2024.8 起停止披露，故以涨跌家数宽度替代市场资金面。</div>

  <footer>
    SENTIO · 舆情采集报告 · 生成于 {gen_time}<br>
    数据源：akshare 官方聚合（东财千股千评/人气榜/个股资金流/沪深股通）· 合规零爬虫<br>
    研究参考工具，不构成投资建议。情绪为概率性反向信号，会出错；股市有风险，风险自负。
  </footer>
</div></body></html>"""

    OUT.write_text(html, encoding="utf-8")
    print(f"报告已生成 → {OUT}")


if __name__ == "__main__":
    main()
