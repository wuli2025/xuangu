<script setup lang="ts">
// 信源板块：把当前实际在采集的信源 + 采集方式编成目录，并支持用户自定义登记自己想关注的渠道。
// 内置信源 = SOURCE_GROUPS（与 data-pipeline 脚本一一对应）；用户信源落 user_sources.json，可增删。
import { computed, onMounted, ref } from "vue";
import { loadUserSources, saveUserSources, type UserSource } from "./useSentio";

type Status = "live" | "partial" | "planned";
interface Source {
  name: string; // 信源名
  provider: string; // 数据提供方
  api: string; // 接口 / akshare 函数
  feeds: string; // 喂给哪一层 / 用途
  method: string; // 采集方式要点
  status: Status;
}
interface SourceGroup {
  key: string;
  title: string;
  desc: string;
  sources: Source[];
}

// ── 当前真实信源目录（与 data-pipeline 脚本一一对应）──
const SOURCE_GROUPS: SourceGroup[] = [
  {
    key: "heat",
    title: "① 情绪热度",
    desc: "全网关注度 / 散户人气 → 情绪温度的「热度 H」分量",
    sources: [
      {
        name: "千股千评 · 关注指数",
        provider: "东方财富",
        api: "ak.stock_comment_em",
        feeds: "热度 H · 关注指数全市场分位 + 千股千评排名",
        method: "akshare 官方聚合 · 强制直连绕代理 · 当日磁盘缓存(TTL 180min)省去分页抓取",
        status: "live",
      },
      {
        name: "人气榜 Top100",
        provider: "东方财富",
        api: "ak.stock_hot_rank_em",
        feeds: "热度 H 加成 · 在榜 +12 分",
        method: "akshare 官方聚合 · 直连 · 随热度缓存一起落盘",
        status: "live",
      },
    ],
  },
  {
    key: "fund",
    title: "② 资金面",
    desc: "主力资金动向 + 市场宽度 → 情绪温度的「资金 F」分量与大盘背景",
    sources: [
      {
        name: "个股主力资金流",
        provider: "东方财富 push2his",
        api: "qt/stock/fflow/daykline（自实现 HTTP）",
        feeds: "资金 F · 主力净流入额 + 净占比",
        method: "只取 f51/f52/f57 最小字段(避 TLS bad record mac) · 并发 6 线程 · requests→curl.exe 兜底 · 连续失败自动熔断降级中性",
        status: "live",
      },
      {
        name: "沪深港通资金流汇总",
        provider: "东方财富",
        api: "ak.stock_hsgt_fund_flow_summary_em",
        feeds: "市场宽度(涨跌家数) + 上证/深证指数涨跌",
        method: "akshare 官方聚合 · 直连。北向实时净流入自 2024.8 起停披露，故用涨跌家数宽度替代市场资金面",
        status: "partial",
      },
    ],
  },
  {
    key: "price",
    title: "③ 行情 / 价格",
    desc: "前复权 K 线 → 斐波那契趋势引擎与多因子策略的回测、寻优、今日选股",
    sources: [
      {
        name: "A 股日线（前复权）· 主源",
        provider: "新浪财经",
        api: "ak.stock_zh_a_daily",
        feeds: "斐波/多因子全历史 K 线主源",
        method: "换新浪 host 避开东财高频/大响应的 TLS 重置 · 一把取前复权全历史",
        status: "live",
      },
      {
        name: "A 股日线 · 兜底",
        provider: "腾讯财经",
        api: "ak.stock_zh_a_hist_tx",
        feeds: "新浪取价失败时自动兜底",
        method: "datastore 增量库内多源回退 · 直连",
        status: "live",
      },
      {
        name: "指数日线",
        provider: "东方财富",
        api: "ak.stock_zh_index_daily",
        feeds: "市场态势 regime 判定",
        method: "直连。实证：指数级 regime 闸对自下而上个股趋势策略无效，默认关，SENTIO_REGIME=1 可开",
        status: "partial",
      },
    ],
  },
  {
    key: "universe",
    title: "④ 股票宇宙",
    desc: "决定「扫哪些票」——选股的候选池来源",
    sources: [
      {
        name: "中证 800 成分",
        provider: "中证指数公司",
        api: "ak.index_stock_cons_csindex",
        feeds: "全市场扩容后的选股宇宙(替代早期 32 龙头幸存者偏差池)",
        method: "中证官源直连 · 落 universe.json",
        status: "live",
      },
      {
        name: "指数成分 · 兜底",
        provider: "新浪",
        api: "ak.index_stock_cons",
        feeds: "中证官源失败时兜底取成分",
        method: "直连",
        status: "live",
      },
      {
        name: "全 A 代码 / 名称表",
        provider: "akshare",
        api: "ak.stock_info_a_code_name",
        feeds: "代码 ↔ 名称 ↔ 板块映射",
        method: "直连",
        status: "live",
      },
    ],
  },
  {
    key: "news",
    title: "⑤ 新闻 & AI 排雷",
    desc: "技术面选出候选后的最后一道关：用真实新闻做利空否决（铁律：防幻觉）",
    sources: [
      {
        name: "个股新闻",
        provider: "东方财富",
        api: "ak.stock_news_em",
        feeds: "候选股近期新闻标题 + 摘要",
        method: "直连。先离线关键词红旗扫描(确定性、零成本)",
        status: "live",
      },
      {
        name: "LLM 深度研判",
        provider: "Claude（左下角供应商坞 API）",
        api: "claude CLI · SENTIO_AI_LLM=1",
        feeds: "仅依据所喂真实新闻判断是否重大利空 → veto",
        method: "严禁用训练记忆/凭空推荐，只读我们喂的新闻；可选开关，不开则只跑关键词红旗",
        status: "live",
      },
    ],
  },
  {
    key: "planned",
    title: "⑥ 规划中 / 待接入",
    desc: "后面想加的信源先登记在这儿，落地后把 status 改成 live",
    sources: [
      {
        name: "文本情感 S（第③层情绪）",
        provider: "DeepSeek / Qwen 等 API",
        api: "—",
        feeds: "情绪温度补齐 S 分量(当前温度只含 H+F)",
        method: "走接入的 API 模型打分，零本地模型",
        status: "planned",
      },
      {
        name: "B 站财经",
        provider: "Bilibili",
        api: "—",
        feeds: "财经 UP 主视频 + 弹幕 + 评论 → 散户情绪增强",
        method: "母体已有「B站调研」flow 基因，待接采集",
        status: "planned",
      },
      {
        name: "雪球讨论热度",
        provider: "雪球",
        api: "—",
        feeds: "个股讨论量 / 情绪倾向",
        method: "待接入",
        status: "planned",
      },
      {
        name: "龙虎榜 / 游资席位",
        provider: "东方财富 / 同花顺",
        api: "—",
        feeds: "席位异动 → 资金面增强",
        method: "待接入",
        status: "planned",
      },
    ],
  },
];

// 采集方法论（贯穿所有信源的统一原则）
const PRINCIPLES = [
  { icon: "🛡️", title: "合规直连", text: "只用 akshare 官方聚合的公开数据，不写爬虫、不绕反爬" },
  { icon: "🔌", title: "绕代理直连", text: "本机 Clash 代理会破坏东财 TLS，脚本强制忽略系统代理直连国内源" },
  { icon: "🪶", title: "最小字段", text: "资金流只取 3 个字段 + curl 兜底，避开大响应触发的 TLS 重置" },
  { icon: "⚡", title: "并发 + 熔断", text: "资金流多线程并发，接口连续失败自动熔断降级，不对死接口死等" },
  { icon: "💾", title: "磁盘缓存", text: "千股千评全市场关注度当日缓存，省掉最慢的分页抓取" },
  { icon: "🧠", title: "AI 防幻觉", text: "LLM 只依据喂给它的真实新闻做判断，绝不凭训练记忆推荐" },
];

const liveCount = computed(
  () =>
    SOURCE_GROUPS.flatMap((g) => g.sources).filter((s) => s.status !== "planned")
      .length
);
const plannedCount = computed(
  () =>
    SOURCE_GROUPS.flatMap((g) => g.sources).filter((s) => s.status === "planned")
      .length
);

const STATUS_LABEL: Record<Status, string> = {
  live: "已接入",
  partial: "部分 / 受限",
  planned: "规划中",
};

// ── 用户自定义信源 ──
const userSources = ref<UserSource[]>([]);
const showAdd = ref(false);
const saveMsg = ref("");
const draft = ref<UserSource>({ name: "", provider: "", api: "", feeds: "", method: "", note: "" });

async function refreshUser() {
  userSources.value = await loadUserSources();
}
function resetDraft() {
  draft.value = { name: "", provider: "", api: "", feeds: "", method: "", note: "" };
}
let saveTimer: number | undefined;
function flash(msg: string) {
  saveMsg.value = msg;
  clearTimeout(saveTimer);
  saveTimer = window.setTimeout(() => (saveMsg.value = ""), 2200);
}
async function addUserSource() {
  const d = draft.value;
  if (!d.name.trim()) {
    flash("请填写信源名称");
    return;
  }
  userSources.value.push({
    name: d.name.trim(),
    provider: d.provider.trim() || "自定义",
    api: d.api?.trim() || "",
    feeds: d.feeds?.trim() || "",
    method: d.method?.trim() || "",
    note: d.note?.trim() || "",
  });
  try {
    await saveUserSources(userSources.value);
    flash("已保存");
    resetDraft();
    showAdd.value = false;
  } catch (e) {
    flash("保存失败：" + e);
  }
}
async function removeUserSource(i: number) {
  userSources.value.splice(i, 1);
  try {
    await saveUserSources(userSources.value);
    flash("已删除");
  } catch (e) {
    flash("保存失败：" + e);
  }
}

onMounted(refreshUser);
</script>

<template>
  <div class="sentio-view">
    <div class="inner">
      <header class="head">
        <div>
          <div class="eyebrow">智投顾 · AI 智能选股舆情终端</div>
          <h1>信源</h1>
        </div>
        <div class="live">
          已接入 {{ liveCount }} 个 · 规划 {{ plannedCount }} 个
        </div>
      </header>
      <p class="sub">
        当前在采集的所有信源，以及每个信源的采集方式。规划中的信源后续接入后把状态改成「已接入」即可。
      </p>

      <!-- 采集方法论 -->
      <div class="sechead">采集方法论 · 贯穿所有信源</div>
      <div class="principles">
        <div v-for="p in PRINCIPLES" :key="p.title" class="pcard">
          <div class="pic">{{ p.icon }}</div>
          <div>
            <div class="pt">{{ p.title }}</div>
            <div class="px">{{ p.text }}</div>
          </div>
        </div>
      </div>

      <!-- 信源目录 -->
      <div v-for="g in SOURCE_GROUPS" :key="g.key" class="group">
        <div class="ghead">
          <span class="gtitle">{{ g.title }}</span>
          <span class="gdesc">{{ g.desc }}</span>
        </div>
        <div class="srclist">
          <div v-for="s in g.sources" :key="s.name" class="srow" :class="s.status">
            <div class="stop">
              <span class="sname">{{ s.name }}</span>
              <span class="sbadge" :class="s.status">{{ STATUS_LABEL[s.status] }}</span>
              <span class="sprov">{{ s.provider }}</span>
            </div>
            <div class="sapi" v-if="s.api && s.api !== '—'"><code>{{ s.api }}</code></div>
            <div class="sfeeds"><b>用于</b>{{ s.feeds }}</div>
            <div class="smethod"><b>采集</b>{{ s.method }}</div>
          </div>
        </div>
      </div>

      <!-- 我的信源（用户自定义登记） -->
      <div class="group">
        <div class="ghead">
          <span class="gtitle">⑦ 我的信源</span>
          <span class="gdesc">你自己想关注的渠道，登记后留存（落 user_sources.json）</span>
          <button class="addbtn" @click="showAdd = !showAdd">{{ showAdd ? "收起" : "＋ 添加信源" }}</button>
        </div>

        <!-- 添加表单 -->
        <div v-if="showAdd" class="addform">
          <div class="frow">
            <input v-model="draft.name" placeholder="信源名称 *（如：同花顺问财热榜）" />
            <input v-model="draft.provider" placeholder="数据提供方（如：同花顺）" />
          </div>
          <div class="frow">
            <input v-model="draft.api" placeholder="接口 / 函数 / 链接（可选）" />
            <input v-model="draft.feeds" placeholder="用于哪一层 / 用途（可选）" />
          </div>
          <input v-model="draft.method" class="full" placeholder="采集方式要点（可选）" />
          <input v-model="draft.note" class="full" placeholder="备注（可选）" />
          <div class="fbtns">
            <button class="btn primary" @click="addUserSource">保存</button>
            <button class="btn ghost" @click="showAdd = false">取消</button>
            <span v-if="saveMsg" class="savemsg">{{ saveMsg }}</span>
          </div>
        </div>
        <div v-else-if="saveMsg" class="savemsg solo">{{ saveMsg }}</div>

        <div class="srclist">
          <div v-for="(s, i) in userSources" :key="i" class="srow live">
            <div class="stop">
              <span class="sname">{{ s.name }}</span>
              <span class="sbadge live">我的</span>
              <span class="sprov">{{ s.provider }}</span>
              <button class="delx" title="删除" @click="removeUserSource(i)">×</button>
            </div>
            <div class="sapi" v-if="s.api"><code>{{ s.api }}</code></div>
            <div class="sfeeds" v-if="s.feeds"><b>用于</b>{{ s.feeds }}</div>
            <div class="smethod" v-if="s.method"><b>采集</b>{{ s.method }}</div>
            <div class="smethod" v-if="s.note"><b>备注</b>{{ s.note }}</div>
          </div>
          <div v-if="!userSources.length" class="srow empty-row">
            还没有自定义信源。点右上角「＋ 添加信源」登记你想关注的渠道。
          </div>
        </div>
      </div>

      <p class="foot">
        想关注更多渠道？直接在上方<b>「⑦ 我的信源」</b>点「＋ 添加信源」登记即可，留存在本机
        <code>user_sources.json</code>。需要真正落地自动采集的，再到 <code>data-pipeline/</code>
        增对应函数并写入 <code>public/sentio/*.json</code>。研究参考，非投资建议。
      </p>
    </div>
  </div>
</template>

<style scoped>
.sentio-view {
  flex: 1;
  height: 100vh;
  overflow-y: auto;
  background: #070a12;
  background-image: radial-gradient(circle at 15% 5%, rgba(91, 140, 255, 0.12), transparent 40%),
    radial-gradient(circle at 85% 12%, rgba(0, 224, 198, 0.1), transparent 42%);
  color: #f0f3fa;
  font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Microsoft YaHei", sans-serif;
  letter-spacing: 0.01em;
}
.inner { max-width: 1000px; margin: 0 auto; padding: 34px 32px 80px; }
.head { display: flex; align-items: flex-end; gap: 16px; margin-bottom: 6px; }
.eyebrow {
  font-size: 12px; font-weight: 600; letter-spacing: 0.06em;
  background: linear-gradient(120deg, #5b8cff, #00e0c6); -webkit-background-clip: text; background-clip: text; color: transparent;
}
h1 { font-size: 32px; font-weight: 800; letter-spacing: -0.02em; margin: 6px 0 0; }
.live {
  margin-left: auto; font-size: 12px; color: #00e69a; display: flex; align-items: center; gap: 7px;
}
.live::before { content: ""; width: 7px; height: 7px; border-radius: 50%; background: #00e69a; box-shadow: 0 0 8px #00e69a; }
.sub { color: #8a93a8; font-size: 13px; margin: 0 0 8px; max-width: 720px; line-height: 1.6; }

.sechead {
  font-size: 13px; font-weight: 700; letter-spacing: 0.04em; color: #8a93a8; margin: 30px 0 12px;
}
.principles { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 12px; }
.pcard {
  display: flex; gap: 12px; align-items: flex-start;
  border: 1px solid rgba(255, 255, 255, 0.09); border-radius: 16px;
  padding: 14px 16px; background: rgba(255, 255, 255, 0.045);
}
.pic { font-size: 20px; line-height: 1; flex-shrink: 0; }
.pt { font-size: 13.5px; font-weight: 700; }
.px { font-size: 12px; color: #8a93a8; margin-top: 4px; line-height: 1.55; }

.group { margin-top: 32px; }
.ghead { display: flex; align-items: baseline; gap: 12px; margin-bottom: 12px; flex-wrap: wrap; }
.gtitle { font-size: 16px; font-weight: 800; }
.gdesc { font-size: 12px; color: #6b7384; }
.srclist {
  border: 1px solid rgba(255, 255, 255, 0.09); border-radius: 18px; overflow: hidden; background: rgba(255, 255, 255, 0.045);
}
.srow { padding: 16px 18px; border-bottom: 1px solid rgba(255, 255, 255, 0.06); }
.srow:last-child { border-bottom: none; }
.srow.planned { opacity: 0.74; }
.srow.planned::before { content: none; }
.stop { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.sname { font-size: 14.5px; font-weight: 700; }
.sprov { font-size: 12px; color: #6b7384; margin-left: auto; }
.sbadge { font-size: 10.5px; font-weight: 700; padding: 2px 9px; border-radius: 980px; }
.sbadge.live { color: #00e69a; background: rgba(0, 230, 154, 0.13); }
.sbadge.partial { color: #ffcf6b; background: rgba(255, 207, 107, 0.13); }
.sbadge.planned { color: #5b8cff; background: rgba(91, 140, 255, 0.14); }
.sapi { margin: 8px 0 2px; }
.sapi code {
  font-family: "SF Mono", Consolas, monospace; font-size: 11.5px; color: #a9d8ff;
  background: rgba(255, 255, 255, 0.06); padding: 2px 9px; border-radius: 6px;
}
.sfeeds, .smethod { font-size: 12.5px; color: #c4cad6; margin-top: 7px; line-height: 1.55; }
.sfeeds b, .smethod b {
  display: inline-block; min-width: 36px; color: #6b7384; font-weight: 600; font-size: 11px; margin-right: 8px;
}
.foot { color: #5c6378; font-size: 12px; margin-top: 30px; line-height: 1.7; }
.foot code {
  font-family: "SF Mono", Consolas, monospace; color: #a9d8ff;
  background: rgba(255, 255, 255, 0.06); padding: 1px 6px; border-radius: 5px; font-size: 11px;
}

/* 我的信源 */
.addbtn {
  margin-left: auto; border: 1px solid rgba(91,140,255,0.4); background: rgba(91,140,255,0.12);
  color: #a9d8ff; font-size: 12px; padding: 5px 12px; border-radius: 8px; cursor: pointer;
}
.addbtn:hover { background: rgba(91,140,255,0.2); }
.addform {
  border: 1px solid rgba(255,255,255,0.1); border-radius: 14px; padding: 14px; margin-bottom: 12px;
  background: rgba(255,255,255,0.04); display: flex; flex-direction: column; gap: 10px;
}
.frow { display: flex; gap: 10px; }
.addform input {
  flex: 1; min-width: 0; background: rgba(0,0,0,0.25); border: 1px solid rgba(255,255,255,0.1);
  border-radius: 8px; color: #f0f3fa; font-size: 13px; padding: 8px 11px;
}
.addform input.full { width: 100%; }
.addform input:focus { outline: none; border-color: #5b8cff; }
.fbtns { display: flex; align-items: center; gap: 10px; }
.btn { border: none; border-radius: 9px; font-size: 13px; padding: 8px 18px; cursor: pointer; }
.btn.primary { background: linear-gradient(120deg, #5b8cff, #00e0c6); color: #04121a; font-weight: 700; }
.btn.ghost { background: rgba(255,255,255,0.07); color: #c4cad6; }
.savemsg { font-size: 12px; color: #00e69a; }
.savemsg.solo { margin-bottom: 10px; }
.delx {
  border: none; background: transparent; color: #6b7384; font-size: 18px; line-height: 1;
  cursor: pointer; padding: 0 2px;
}
.delx:hover { color: #ff5470; }
.empty-row { color: #6b7384; font-size: 12.5px; }

</style>
