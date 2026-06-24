<script setup lang="ts">
// 自选诊断：你手输/维护一组股票 → 基于【真实落库行情】给「能否买/动作/时机/价位」+ 多策略契合度。
// 全部数字来自 datastore 真实日线，每张卡带「✓ 真实数据」戳，可逐项核对，从根上防 AI 幻觉。
import { ref, onMounted, computed, onUnmounted } from "vue";
import {
  loadDiagnose, runDiag, onDiagProgress, onDiagDone,
  loadMyWatchlist, saveMyWatchlist, loadHoldings, saveHoldings,
  type Diagnose, type Diagnosis, type MyStock, type Holding,
} from "./useSentio";
import { useProvidersStore } from "../../stores/providers";

const emit = defineEmits<{ (e: "open-report", code: string): void }>();

const providers = useProvidersStore();
const apiName = computed(() => providers.current?.name || "当前 API");
const aiDeep = ref(false);

const data = ref<Diagnose | null>(null);
const loading = ref(true);
const running = ref(false);
const pct = ref(0);
const lastMsg = ref("");
const codesInput = ref("");

// 自选股 / 持仓（账户管理基座）
const myList = ref<MyStock[]>([]);
const holdings = ref<Holding[]>([]);
const showManage = ref(false);
const newCode = ref("");
const newHoldCode = ref("");
const newHoldCost = ref("");
const newHoldShares = ref("");
const saveMsg = ref("");

let offProg: Promise<() => void> | null = null;
let offDone: Promise<() => void> | null = null;

async function refresh() {
  loading.value = true;
  const [d, w, h] = await Promise.all([loadDiagnose(), loadMyWatchlist(), loadHoldings()]);
  data.value = d;
  myList.value = w;
  holdings.value = h;
  loading.value = false;
}

// 解析输入框里的代码（支持空格/逗号/换行/中文逗号分隔，提取 6 位数字）
function parseCodes(s: string): string[] {
  return Array.from(new Set((s.match(/\d{6}/g) ?? [])));
}

async function runNow() {
  if (running.value) return;
  const codes = parseCodes(codesInput.value);
  // 没输入就诊断自选股；自选也空则后端回退默认演示集
  running.value = true;
  pct.value = 2;
  lastMsg.value = "启动诊断…";
  try {
    await runDiag(codes.length ? codes : undefined, aiDeep.value);
  } catch (e) {
    running.value = false;
    lastMsg.value = String(e);
  }
}

// 把输入框里的代码加入自选并保存
async function addToWatchlist() {
  const codes = parseCodes(codesInput.value || newCode.value);
  if (!codes.length) return;
  const exist = new Set(myList.value.map((s) => s.code));
  for (const c of codes) if (!exist.has(c)) myList.value.push({ code: c });
  await persistWatchlist();
  newCode.value = "";
}
async function removeFromWatchlist(code: string) {
  myList.value = myList.value.filter((s) => s.code !== code);
  await persistWatchlist();
}
async function persistWatchlist() {
  try {
    await saveMyWatchlist(myList.value);
    flashSave("自选已保存");
  } catch (e) {
    flashSave("保存失败：" + e);
  }
}

async function addHolding() {
  const codes = parseCodes(newHoldCode.value);
  if (!codes.length) return;
  const code = codes[0];
  const cost = parseFloat(newHoldCost.value) || null;
  const shares = parseFloat(newHoldShares.value) || 0;
  holdings.value = holdings.value.filter((h) => h.code !== code);
  holdings.value.push({ code, cost, shares });
  await persistHoldings();
  newHoldCode.value = newHoldCost.value = newHoldShares.value = "";
}
async function removeHolding(code: string) {
  holdings.value = holdings.value.filter((h) => h.code !== code);
  await persistHoldings();
}
async function persistHoldings() {
  try {
    await saveHoldings(holdings.value);
    flashSave("持仓已保存");
  } catch (e) {
    flashSave("保存失败：" + e);
  }
}
let saveTimer: number | undefined;
function flashSave(msg: string) {
  saveMsg.value = msg;
  clearTimeout(saveTimer);
  saveTimer = window.setTimeout(() => (saveMsg.value = ""), 2200);
}

function fillFromWatchlist() {
  codesInput.value = myList.value.map((s) => s.code).join(" ");
}

onMounted(() => {
  refresh();
  providers.refresh();
  offProg = onDiagProgress((p) => {
    if (p.pct >= 0) pct.value = p.pct;
    lastMsg.value = p.line;
  });
  offDone = onDiagDone((d) => {
    running.value = false;
    pct.value = 100;
    lastMsg.value = d.message;
    if (d.ok) refresh();
  });
});
onUnmounted(() => {
  offProg?.then((f) => f());
  offDone?.then((f) => f());
});

const diags = computed(() => data.value?.diagnoses?.filter((d) => !d.error) ?? []);
const errs = computed(() => data.value?.diagnoses?.filter((d) => d.error) ?? []);
const updated = computed(() =>
  data.value?.updated_at ? data.value.updated_at.replace("T", " ").slice(0, 16) : ""
);

const TIER: Record<string, { label: string; color: string }> = {
  buy: { label: "买入/低吸", color: "#00e69a" },
  hold: { label: "持有/加仓", color: "#33e0ff" },
  wait: { label: "观望等待", color: "#8a93a8" },
  warn: { label: "减仓/止盈", color: "#ffcf6b" },
  danger: { label: "回避/不碰", color: "#ff5470" },
};
function tierMeta(t: string) {
  return TIER[t] ?? TIER.wait;
}
// 动作分组计数
const counts = computed(() => {
  const c: Record<string, number> = {};
  for (const d of diags.value) c[d.tier] = (c[d.tier] ?? 0) + 1;
  return c;
});

function fitColor(fit: number): string {
  if (fit >= 75) return "#00e69a";
  if (fit >= 55) return "#33e0ff";
  if (fit >= 40) return "#ffcf6b";
  return "#8a93a8";
}
function confColor(c: number): string {
  if (c >= 70) return "#00e69a";
  if (c >= 45) return "#ffcf6b";
  return "#ff5470";
}
function pfText(d: Diagnosis): string {
  if (!d.hist) return "无足够历史交易";
  const pf = d.hist.profit_factor;
  return `回测 ${d.hist.trades} 笔 · 胜率 ${d.hist.win_rate}% · 期望 ${d.hist.expectancy_r}R · 盈亏比 ${pf ?? "—"}`;
}

// 卖出时机紧迫度 → 标签 + 颜色
const EXIT_URGENCY: Record<string, { label: string; color: string }> = {
  now: { label: "尽快卖出", color: "#ff5470" },
  soon: { label: "临近卖点", color: "#ffcf6b" },
  trail: { label: "移动止盈持有", color: "#33e0ff" },
  hold: { label: "按纪律持有", color: "#8a93a8" },
  na: { label: "暂无卖点", color: "#8a93a8" },
};
function exitMeta(u: string) {
  return EXIT_URGENCY[u] ?? EXIT_URGENCY.hold;
}
</script>

<template>
  <div class="sentio-view">
    <div class="inner">
      <header class="head">
        <div>
          <div class="eyebrow">智投顾 · AI 智能选股</div>
          <h1>自选诊断</h1>
        </div>
        <div class="live" v-if="updated">数据更新 {{ updated }}</div>
      </header>
      <p class="sub">
        输入你关心的股票代码（6 位，空格/逗号/换行分隔），基于<b>真实落库行情</b>给出
        「能不能买 · 现在做什么 · 什么时候操作 · 到什么价位」+ 四套策略契合度。
        每只都带<b>「✓ 真实数据」戳</b>，数字均来自新浪/腾讯前复权日线，可逐项核对，绝不臆造。
      </p>

      <!-- 输入区 -->
      <div class="panel">
        <textarea
          v-model="codesInput"
          class="codes"
          rows="2"
          placeholder="例：600519 300750 000858  （留空则诊断你的自选股）"
        ></textarea>
        <div class="ctrls">
          <button class="btn primary" :disabled="running" @click="runNow">
            {{ running ? "诊断中…" : "开始诊断" }}
          </button>
          <button class="btn ghost" :disabled="running" @click="addToWatchlist">＋加入自选</button>
          <button class="btn ghost" :disabled="!myList.length" @click="fillFromWatchlist">用自选填入</button>
          <label class="ai-toggle" :title="`开启后用「${apiName}」基于真实新闻对诊断到的票做利空排雷`">
            <input type="checkbox" v-model="aiDeep" :disabled="running" />
            <span>AI 新闻排雷（{{ apiName }}）</span>
          </label>
          <button class="btn link" @click="showManage = !showManage">
            {{ showManage ? "收起" : "管理自选 / 持仓" }}
          </button>
        </div>
        <div v-if="running || pct > 0" class="prog">
          <div class="bar"><div class="fill" :style="{ width: pct + '%' }"></div></div>
          <div class="pmsg">{{ lastMsg }}</div>
        </div>
        <div v-if="saveMsg" class="savemsg">{{ saveMsg }}</div>
      </div>

      <!-- 自选 / 持仓管理 -->
      <div v-if="showManage" class="manage">
        <div class="mcol">
          <div class="mtitle">我的自选股 <span>{{ myList.length }}</span></div>
          <div class="chips">
            <span v-for="s in myList" :key="s.code" class="chip">
              {{ s.code }}<i @click="removeFromWatchlist(s.code)">×</i>
            </span>
            <span v-if="!myList.length" class="empty">还没有自选股，输入代码点「＋加入自选」</span>
          </div>
          <div class="addrow">
            <input v-model="newCode" placeholder="代码" @keyup.enter="addToWatchlist" />
            <button class="btn ghost sm" @click="addToWatchlist">添加</button>
          </div>
        </div>
        <div class="mcol">
          <div class="mtitle">
            我的持仓 <span>{{ holdings.length }}</span>
            <em>· 登记成本后，诊断会按你的盈亏给止盈/止损建议</em>
          </div>
          <div class="hlist">
            <div v-for="h in holdings" :key="h.code" class="hrow">
              <b>{{ h.code }}</b>
              <span>成本 {{ h.cost ?? "—" }}</span>
              <span>{{ h.shares || 0 }} 股</span>
              <i @click="removeHolding(h.code)">×</i>
            </div>
            <div v-if="!holdings.length" class="empty">未登记持仓</div>
          </div>
          <div class="addrow">
            <input v-model="newHoldCode" placeholder="代码" />
            <input v-model="newHoldCost" placeholder="成本价" />
            <input v-model="newHoldShares" placeholder="股数" />
            <button class="btn ghost sm" @click="addHolding">登记</button>
          </div>
        </div>
      </div>

      <!-- 动作汇总 -->
      <div v-if="diags.length" class="summary">
        <div v-for="(label, key) in (data?.actions_legend ?? {})" :key="key" class="scell"
             :style="{ '--c': tierMeta(key as string).color }">
          <div class="snum">{{ counts[key as string] ?? 0 }}</div>
          <div class="slabel">{{ label }}</div>
        </div>
      </div>

      <!-- 加载 / 空态 -->
      <div v-if="loading" class="hint">加载中…</div>
      <div v-else-if="!diags.length && !errs.length" class="hint">
        还没有诊断结果。输入代码点「开始诊断」即可（首次取价约每只 1–2 秒）。
      </div>

      <!-- 诊断卡片 -->
      <div class="cards">
        <div v-for="d in diags" :key="d.code" class="card" :style="{ '--tier': tierMeta(d.tier).color }">
          <div class="ctop">
            <div class="cleft">
              <span class="abadge">{{ tierMeta(d.tier).label }}</span>
              <span class="cname" @click="emit('open-report', d.code)">{{ d.name }}</span>
              <span class="ccode">{{ d.code }}</span>
              <span v-if="d.sector" class="csector">{{ d.sector }}</span>
            </div>
            <div class="conf" :style="{ color: confColor(d.confidence) }">
              <span class="cv">{{ d.confidence }}</span><span class="cl">信心</span>
            </div>
          </div>

          <div class="verdict">{{ d.verdict }}</div>
          <div class="timing"><b>时机</b>{{ d.timing }}</div>

          <!-- 价位 -->
          <div class="levels">
            <div class="lv"><span>入场</span><b>{{ d.entry ?? "—" }}</b></div>
            <div class="lv"><span>止损</span><b class="red">{{ d.stop }}</b><i>{{ d.stop_pct }}%</i></div>
            <div class="lv" v-if="d.target1"><span>目标①</span><b class="grn">{{ d.target1 }}</b></div>
            <div class="lv" v-if="d.target2"><span>目标②</span><b class="grn">{{ d.target2 }}</b><i v-if="d.upside_pct">+{{ d.upside_pct }}%</i></div>
            <div class="lv"><span>现价</span><b>{{ d.factors.close }}</b></div>
            <div class="lv"><span>阻力(250高)</span><b>{{ d.struct_target }}</b></div>
          </div>

          <!-- 持仓视角 -->
          <div v-if="d.position_note" class="posnote">
            <b>持仓</b>{{ d.position_note }}
          </div>

          <!-- 卖出时机：什么时候卖最好 -->
          <div v-if="d.best_exit" class="exit" :style="{ '--ec': exitMeta(d.best_exit.urgency).color }">
            <div class="ehead">
              <span class="etag">卖出时机</span>
              <span class="eurg">{{ exitMeta(d.best_exit.urgency).label }}</span>
            </div>
            <div class="ehl">{{ d.best_exit.headline }}</div>
            <div v-if="d.best_exit.advice" class="eadvice">
              <b>你的持仓</b>{{ d.best_exit.advice }}
            </div>
            <div class="elevels">
              <div class="el"><span>移动止盈</span><b class="cyan">{{ d.best_exit.trail_stop }}</b></div>
              <div class="el" v-if="d.best_exit.take_profit_1"><span>止盈①</span><b class="grn">{{ d.best_exit.take_profit_1 }}</b></div>
              <div class="el" v-if="d.best_exit.take_profit_2"><span>止盈②</span><b class="grn">{{ d.best_exit.take_profit_2 }}</b></div>
              <div class="el"><span>硬止损</span><b class="red">{{ d.best_exit.hard_stop }}</b></div>
            </div>
            <ul class="etrig">
              <li v-for="(t, ti) in d.best_exit.triggers" :key="ti">{{ t }}</li>
            </ul>
          </div>

          <!-- 多策略契合度 -->
          <div class="strats">
            <div v-for="s in d.strategies" :key="s.key" class="srow">
              <div class="stitle">
                <span class="sn">{{ s.name }}</span>
                <span class="stier">{{ s.tier }}</span>
                <span class="saction" :style="{ color: fitColor(s.fit) }">{{ s.action }}</span>
              </div>
              <div class="sbar"><div class="sfill" :style="{ width: s.fit + '%', background: fitColor(s.fit) }"></div></div>
            </div>
          </div>

          <!-- 关键因子 -->
          <div class="facts">
            <span>RSI {{ d.factors.rsi }}</span>
            <span>20日 {{ d.factors.r20 }}%</span>
            <span>60日 {{ d.factors.r60 }}%</span>
            <span>波动 {{ d.factors.vol_ann }}%</span>
            <span>区间位 {{ d.factors.pos_in_range }}%</span>
            <span v-if="d.factors.bull_align" class="ok">多头排列</span>
            <span v-if="d.factors.below_ma120" class="bad">破年线</span>
          </div>

          <!-- 该股历史回测真实战绩（防空话） -->
          <div class="hist">{{ pfText(d) }}</div>

          <!-- 数据真实性戳 -->
          <div class="prov" :title="d.provenance.source">
            <span class="ok-dot"></span>真实数据 ·
            {{ d.provenance.bars }} 根K线 ·
            {{ d.provenance.first_date }} → {{ d.provenance.last_date }} ·
            收盘 {{ d.provenance.last_close }}
          </div>
        </div>
      </div>

      <!-- 取价失败的 -->
      <div v-if="errs.length" class="errs">
        <div class="ehead">未能诊断（{{ errs.length }}）</div>
        <div v-for="e in errs" :key="e.code" class="erow">{{ e.code }} · {{ e.error }}</div>
      </div>

      <p class="foot" v-if="data?.disclaimer">{{ data.disclaimer }}</p>
    </div>
  </div>
</template>

<style scoped>
.sentio-view {
  flex: 1; height: 100vh; overflow-y: auto; background: #070a12;
  background-image: radial-gradient(circle at 15% 5%, rgba(91, 140, 255, 0.12), transparent 40%),
    radial-gradient(circle at 85% 12%, rgba(0, 224, 198, 0.1), transparent 42%);
  color: #f0f3fa; font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Microsoft YaHei", sans-serif;
}
.inner { max-width: 1040px; margin: 0 auto; padding: 34px 32px 80px; }
.head { display: flex; align-items: flex-end; gap: 16px; margin-bottom: 6px; }
.eyebrow {
  font-size: 12px; font-weight: 600; letter-spacing: 0.06em;
  background: linear-gradient(120deg, #5b8cff, #00e0c6); -webkit-background-clip: text; background-clip: text; color: transparent;
}
h1 { font-size: 32px; font-weight: 800; letter-spacing: -0.02em; margin: 6px 0 0; }
.live { margin-left: auto; font-size: 12px; color: #8a93a8; }
.sub { color: #8a93a8; font-size: 13px; margin: 0 0 18px; max-width: 760px; line-height: 1.7; }
.sub b { color: #c4cad6; }

.panel { border: 1px solid rgba(255,255,255,0.09); border-radius: 16px; padding: 14px; background: rgba(255,255,255,0.045); }
.codes {
  width: 100%; box-sizing: border-box; background: rgba(0,0,0,0.25); border: 1px solid rgba(255,255,255,0.1);
  border-radius: 10px; color: #f0f3fa; font-size: 15px; padding: 10px 12px; resize: vertical;
  font-family: "SF Mono", Consolas, monospace; letter-spacing: 0.5px;
}
.codes:focus { outline: none; border-color: #5b8cff; }
.ctrls { display: flex; align-items: center; gap: 10px; margin-top: 10px; flex-wrap: wrap; }
.btn { border: none; border-radius: 9px; font-size: 13px; padding: 8px 16px; cursor: pointer; transition: 0.15s; }
.btn.primary { background: linear-gradient(120deg, #5b8cff, #00e0c6); color: #04121a; font-weight: 700; }
.btn.primary:disabled { opacity: 0.5; cursor: default; }
.btn.ghost { background: rgba(255,255,255,0.07); color: #c4cad6; }
.btn.ghost:hover { background: rgba(255,255,255,0.12); }
.btn.ghost.sm { padding: 6px 12px; font-size: 12px; }
.btn.link { background: transparent; color: #5b8cff; margin-left: auto; }
.ai-toggle { display: inline-flex; align-items: center; gap: 6px; font-size: 12px; color: #8a93a8; cursor: pointer; }
.prog { margin-top: 12px; }
.bar { height: 5px; background: rgba(255,255,255,0.08); border-radius: 4px; overflow: hidden; }
.fill { height: 100%; background: linear-gradient(90deg, #5b8cff, #00e0c6); transition: width 0.3s; }
.pmsg { font-size: 11.5px; color: #8a93a8; margin-top: 6px; font-family: "SF Mono", Consolas, monospace; }
.savemsg { font-size: 12px; color: #00e69a; margin-top: 8px; }

.manage { display: grid; grid-template-columns: 1fr 1.2fr; gap: 14px; margin-top: 14px; }
@media (max-width: 760px) { .manage { grid-template-columns: 1fr; } }
.mcol { border: 1px solid rgba(255,255,255,0.09); border-radius: 14px; padding: 14px; background: rgba(255,255,255,0.035); }
.mtitle { font-size: 13px; font-weight: 700; margin-bottom: 10px; }
.mtitle span { color: #5b8cff; margin-left: 4px; }
.mtitle em { color: #6b7384; font-weight: 400; font-style: normal; font-size: 11px; }
.chips { display: flex; flex-wrap: wrap; gap: 6px; min-height: 24px; }
.chip {
  display: inline-flex; align-items: center; gap: 5px; background: rgba(91,140,255,0.15);
  color: #a9d8ff; font-size: 12px; padding: 3px 8px; border-radius: 7px; font-family: "SF Mono", Consolas, monospace;
}
.chip i { cursor: pointer; color: #8a93a8; font-style: normal; }
.chip i:hover { color: #ff5470; }
.empty { color: #6b7384; font-size: 12px; }
.addrow { display: flex; gap: 6px; margin-top: 10px; }
.addrow input {
  flex: 1; min-width: 0; background: rgba(0,0,0,0.25); border: 1px solid rgba(255,255,255,0.1);
  border-radius: 8px; color: #f0f3fa; font-size: 12px; padding: 6px 9px;
}
.addrow input:focus { outline: none; border-color: #5b8cff; }
.hlist { display: flex; flex-direction: column; gap: 5px; }
.hrow { display: flex; align-items: center; gap: 12px; font-size: 12.5px; color: #c4cad6; }
.hrow b { color: #f0f3fa; font-family: "SF Mono", Consolas, monospace; }
.hrow i { margin-left: auto; cursor: pointer; color: #8a93a8; font-style: normal; }
.hrow i:hover { color: #ff5470; }

.summary { display: flex; gap: 10px; margin: 22px 0 8px; flex-wrap: wrap; }
.scell {
  flex: 1; min-width: 90px; border: 1px solid rgba(255,255,255,0.08); border-top: 2px solid var(--c);
  border-radius: 12px; padding: 12px; text-align: center; background: rgba(255,255,255,0.03);
}
.snum { font-size: 24px; font-weight: 800; color: var(--c); }
.slabel { font-size: 11.5px; color: #8a93a8; margin-top: 2px; }

.hint { color: #8a93a8; font-size: 13px; padding: 30px 0; text-align: center; }

.cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(440px, 1fr)); gap: 14px; margin-top: 14px; }
@media (max-width: 560px) { .cards { grid-template-columns: 1fr; } }
.card {
  border: 1px solid rgba(255,255,255,0.09); border-left: 3px solid var(--tier); border-radius: 16px;
  padding: 16px 18px; background: rgba(255,255,255,0.045);
}
.ctop { display: flex; align-items: center; gap: 10px; }
.cleft { display: flex; align-items: center; gap: 9px; flex-wrap: wrap; }
.abadge { font-size: 11px; font-weight: 700; color: var(--tier); background: color-mix(in srgb, var(--tier) 16%, transparent); padding: 3px 10px; border-radius: 980px; }
.cname { font-size: 16px; font-weight: 700; cursor: pointer; }
.cname:hover { color: #5b8cff; }
.ccode { font-size: 12px; color: #6b7384; font-family: "SF Mono", Consolas, monospace; }
.csector { font-size: 11px; color: #8a93a8; background: rgba(255,255,255,0.06); padding: 2px 7px; border-radius: 6px; }
.conf { margin-left: auto; display: flex; flex-direction: column; align-items: center; line-height: 1; }
.conf .cv { font-size: 22px; font-weight: 800; }
.conf .cl { font-size: 10px; color: #6b7384; margin-top: 2px; }
.verdict { font-size: 14px; font-weight: 600; margin: 12px 0 6px; color: #e8ecf4; }
.timing { font-size: 12.5px; color: #c4cad6; line-height: 1.6; }
.timing b, .posnote b { display: inline-block; min-width: 34px; color: #6b7384; font-weight: 600; font-size: 11px; margin-right: 6px; }

.levels { display: flex; flex-wrap: wrap; gap: 7px; margin: 12px 0; }
.lv { background: rgba(0,0,0,0.22); border-radius: 9px; padding: 6px 11px; display: flex; align-items: baseline; gap: 5px; }
.lv span { font-size: 10.5px; color: #6b7384; }
.lv b { font-size: 14px; font-family: "SF Mono", Consolas, monospace; }
.lv b.red { color: #ff5470; }
.lv b.grn { color: #00e69a; }
.lv i { font-size: 10.5px; color: #8a93a8; font-style: normal; }

.posnote { font-size: 12.5px; color: #ffcf6b; background: rgba(255,207,107,0.08); border-radius: 9px; padding: 8px 11px; margin-bottom: 10px; line-height: 1.55; }

.exit {
  border: 1px solid color-mix(in srgb, var(--ec) 35%, transparent);
  border-left: 3px solid var(--ec);
  background: color-mix(in srgb, var(--ec) 7%, transparent);
  border-radius: 11px; padding: 11px 13px; margin: 12px 0;
}
.ehead { display: flex; align-items: center; gap: 9px; margin-bottom: 7px; }
.etag { font-size: 11px; font-weight: 700; color: #8a93a8; letter-spacing: 0.04em; }
.eurg { font-size: 11px; font-weight: 700; color: var(--ec); background: color-mix(in srgb, var(--ec) 16%, transparent); padding: 2px 9px; border-radius: 980px; }
.ehl { font-size: 12.5px; color: #e8ecf4; line-height: 1.6; }
.eadvice { font-size: 12px; color: #ffcf6b; line-height: 1.55; margin-top: 7px; }
.eadvice b { color: #6b7384; font-weight: 600; font-size: 11px; margin-right: 6px; }
.elevels { display: flex; flex-wrap: wrap; gap: 7px; margin: 9px 0 4px; }
.el { background: rgba(0,0,0,0.22); border-radius: 8px; padding: 5px 10px; display: flex; align-items: baseline; gap: 5px; }
.el span { font-size: 10.5px; color: #6b7384; }
.el b { font-size: 13px; font-family: "SF Mono", Consolas, monospace; }
.el b.red { color: #ff5470; }
.el b.grn { color: #00e69a; }
.el b.cyan { color: #33e0ff; }
.etrig { margin: 6px 0 0; padding-left: 16px; }
.etrig li { font-size: 11.5px; color: #9aa3b5; line-height: 1.7; }


.strats { display: flex; flex-direction: column; gap: 8px; margin: 12px 0; }
.srow { }
.stitle { display: flex; align-items: center; gap: 8px; margin-bottom: 4px; }
.sn { font-size: 12.5px; font-weight: 600; }
.stier { font-size: 10.5px; color: #6b7384; }
.saction { font-size: 11px; margin-left: auto; }
.sbar { height: 5px; background: rgba(255,255,255,0.07); border-radius: 4px; overflow: hidden; }
.sfill { height: 100%; border-radius: 4px; transition: width 0.4s; }

.facts { display: flex; flex-wrap: wrap; gap: 6px; margin: 10px 0; }
.facts span { font-size: 11px; color: #8a93a8; background: rgba(255,255,255,0.05); padding: 2px 8px; border-radius: 6px; }
.facts .ok { color: #00e69a; background: rgba(0,230,154,0.1); }
.facts .bad { color: #ff5470; background: rgba(255,84,112,0.1); }
.hist { font-size: 11.5px; color: #8a93a8; padding-top: 8px; border-top: 1px solid rgba(255,255,255,0.06); }
.prov {
  font-size: 10.5px; color: #00e69a; margin-top: 8px; display: flex; align-items: center; gap: 6px; flex-wrap: wrap;
  font-family: "SF Mono", Consolas, monospace;
}
.ok-dot { width: 7px; height: 7px; border-radius: 50%; background: #00e69a; box-shadow: 0 0 7px #00e69a; }

.errs { margin-top: 18px; border: 1px solid rgba(255,84,112,0.2); border-radius: 12px; padding: 12px 14px; }
.ehead { font-size: 12.5px; font-weight: 700; color: #ff5470; margin-bottom: 6px; }
.erow { font-size: 12px; color: #8a93a8; }
.foot { color: #5c6378; font-size: 11.5px; margin-top: 28px; line-height: 1.7; }
</style>
