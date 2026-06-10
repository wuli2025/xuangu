<script setup lang="ts">
import { ref, onMounted, computed, watch as vueWatch } from "vue";
import { storeToRefs } from "pinia";
import { useAppStore } from "../../stores/app";
import { loadStocks, tempColor, adviceOf, schoolFit, type StockRec } from "./useSentio";

const app = useAppStore();
const { sentioStock } = storeToRefs(app);

interface WatchItem {
  code: string;
  name: string;
}
const WATCH_KEY = "zhitougu:watchlist:v1";

const stocks = ref<StockRec[]>([]);
const loading = ref(true);
const watch = ref<WatchItem[]>([]);
const selected = ref<string | null>(null); // 当前点开详情的代码
const addInput = ref("");

function loadWatch(): WatchItem[] {
  try {
    const raw = localStorage.getItem(WATCH_KEY);
    if (raw) return JSON.parse(raw) as WatchItem[];
  } catch {
    /* ignore */
  }
  return [];
}
function persist() {
  try {
    localStorage.setItem(WATCH_KEY, JSON.stringify(watch.value));
  } catch {
    /* ignore */
  }
}

async function refresh() {
  loading.value = true;
  stocks.value = await loadStocks();
  loading.value = false;
  // 首次：用已采集的个股初始化自选列表
  const saved = loadWatch();
  if (saved.length) {
    watch.value = saved;
  } else {
    watch.value = stocks.value.map((r) => ({ code: r.code, name: r.name }));
    persist();
  }
  // 从看板/雷达点击进来时，自动选中并展开该股
  if (sentioStock.value) selectFromExternal(sentioStock.value);
}
onMounted(refresh);

// 看板/雷达点「生成报告」→ openReport(code)，这里确保该股在自选里并展开详情
function selectFromExternal(code: string) {
  const hit = stocks.value.find((r) => r.code === code);
  if (hit && !watch.value.some((w) => w.code === code)) {
    watch.value = [...watch.value, { code: hit.code, name: hit.name }];
    persist();
  }
  selected.value = code;
}
vueWatch(sentioStock, (code) => {
  if (code) selectFromExternal(code);
});

// code → 已采集的情绪数据（可能不存在）
function recOf(code: string): StockRec | undefined {
  return stocks.value.find((r) => r.code === code);
}

function addStock() {
  const q = addInput.value.trim();
  if (!q) return;
  // 命中已采集数据（按代码或名称）则取其真实代码/名称，否则原样加入（标记待采集）
  const hit = stocks.value.find((r) => r.code === q || r.name === q || r.name.includes(q));
  const item: WatchItem = hit
    ? { code: hit.code, name: hit.name }
    : { code: q, name: q };
  if (watch.value.some((w) => w.code === item.code)) {
    addInput.value = "";
    return; // 已在列表
  }
  watch.value = [...watch.value, item];
  persist();
  addInput.value = "";
}

function removeStock(code: string) {
  watch.value = watch.value.filter((w) => w.code !== code);
  if (selected.value === code) selected.value = null;
  persist();
}

function toggle(code: string) {
  selected.value = selected.value === code ? null : code;
}

const cur = computed(() => (selected.value ? recOf(selected.value) : null));
const c = computed(() => (cur.value ? tempColor(cur.value.temperature) : "#8a93a8"));
const adv = computed(() => (cur.value ? adviceOf(cur.value) : null));
const ringPct = computed(() => Math.max(0, Math.min(100, cur.value?.temperature ?? 0)));
const evidence = computed(() => (cur.value ? Object.entries(cur.value.evidence) : []));
const selectedName = computed(() => watch.value.find((w) => w.code === selected.value)?.name || selected.value);
</script>

<template>
  <div class="sentio-view">
    <div class="inner">
      <header class="head">
        <div>
          <div class="eyebrow">智投顾 · 个股报告</div>
          <h1>自选股 · 情绪报告</h1>
        </div>
        <button class="refresh" @click="refresh">刷新</button>
      </header>

      <!-- 添加自选股 -->
      <form class="addbar" @submit.prevent="addStock">
        <input v-model="addInput" placeholder="填写代码或名称添加自选，如 688981 / 中芯国际" />
        <button type="submit" class="add-btn">+ 添加</button>
      </form>

      <div v-if="loading" class="empty">载入采集数据…</div>
      <template v-else>
        <div class="sechead">我的自选 · {{ watch.length }} 只（点击查看详情）</div>
        <div v-if="!watch.length" class="empty small">还没有自选股，用上方输入框添加。</div>

        <!-- 自选列表 -->
        <div class="list">
          <div v-for="w in watch" :key="w.code">
            <div
              class="row"
              :class="{ open: selected === w.code }"
              @click="toggle(w.code)"
            >
              <span class="caret">{{ selected === w.code ? "▾" : "▸" }}</span>
              <span class="nm">{{ w.name }}<small>{{ w.code }}<template v-if="recOf(w.code)"> · {{ recOf(w.code)!.sector }}</template></small></span>
              <template v-if="recOf(w.code)">
                <span class="lvl" :style="{ color: tempColor(recOf(w.code)!.temperature) }">{{ recOf(w.code)!.level }}</span>
                <span class="temp" :style="{ color: tempColor(recOf(w.code)!.temperature) }">{{ recOf(w.code)!.temperature.toFixed(0) }}</span>
              </template>
              <span v-else class="pending">待采集</span>
              <button class="del" title="删除自选" @click.stop="removeStock(w.code)">×</button>
            </div>

            <!-- 点击展开的详情 -->
            <div v-if="selected === w.code" class="detail">
              <template v-if="cur">
                <div class="report" :style="{ '--c': c }">
                  <div class="rep-head">
                    <div class="name">{{ cur.name }} <small>{{ cur.code }} · {{ cur.sector }}</small></div>
                    <div class="school">{{ schoolFit(cur) }}</div>
                    <div class="verdict">{{ adv?.verdict }}</div>
                  </div>
                  <div class="rep-body">
                    <div class="ring-wrap">
                      <div class="ring" :style="{ background: `conic-gradient(var(--c) 0 ${ringPct}%, rgba(255,255,255,.08) ${ringPct}% 100%)` }">
                        <div class="num">{{ cur.temperature.toFixed(0) }}</div>
                      </div>
                      <div class="lab">情绪温度</div>
                      <div class="sig">{{ cur.level }}</div>
                    </div>
                    <div class="advice">
                      <div class="arow"><span class="k">结论</span><span class="vv">{{ adv?.action }}</span></div>
                      <div class="arow"><span class="k">仓位</span><span class="vv">{{ adv?.position }}</span></div>
                      <div class="arow"><span class="k">止损</span><span class="vv">{{ adv?.stop }}</span></div>
                      <div class="arow"><span class="k">止盈</span><span class="vv">{{ adv?.target }}</span></div>
                      <div class="arow reverse"><span class="k">反向提示</span><span class="vv">{{ cur.signal }}</span></div>
                    </div>
                  </div>
                  <div class="bars">
                    <div class="bar">
                      <span class="bl">热度 H</span>
                      <span class="btrk"><i :style="{ width: cur.breakdown.热度H + '%', background: 'linear-gradient(90deg,#5b8cff,#00e0c6)' }"></i></span>
                      <span class="bv">{{ cur.breakdown.热度H.toFixed(0) }}</span>
                    </div>
                    <div class="bar">
                      <span class="bl">资金 F</span>
                      <span class="btrk"><i :style="{ width: cur.breakdown.资金F + '%', background: 'linear-gradient(90deg,#00e69a,#33e0ff)' }"></i></span>
                      <span class="bv">{{ cur.breakdown.资金F.toFixed(0) }}</span>
                    </div>
                    <div class="bar dim">
                      <span class="bl">情感 S</span><span class="btrk"></span><span class="bv">— 待接</span>
                    </div>
                  </div>
                  <div class="evs">
                    <div v-for="[k, v] in evidence" :key="k" class="ev"><span class="ek">{{ k }}</span><span class="evv">{{ v }}</span></div>
                  </div>
                </div>
              </template>
              <div v-else class="nodata">
                「{{ selectedName }}」暂无采集数据。把它加入 <code>data-pipeline/watchlist.json</code> 后运行 <code>python collect.py</code> 即可。
              </div>
            </div>
          </div>
        </div>

        <p class="foot">温度 = 0.40·热度 + 0.35·资金（情感待接入）。情绪为<b>概率性反向信号</b>，研究参考，不构成投资建议。</p>
      </template>
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
.inner { max-width: 940px; margin: 0 auto; padding: 34px 32px 80px; }
.head { display: flex; align-items: flex-end; gap: 16px; margin-bottom: 20px; }
.eyebrow { font-size: 12px; font-weight: 600; letter-spacing: 0.06em; background: linear-gradient(120deg, #5b8cff, #00e0c6); -webkit-background-clip: text; background-clip: text; color: transparent; }
h1 { font-size: 30px; font-weight: 800; letter-spacing: -0.02em; margin: 6px 0 0; }
.refresh { margin-left: auto; font-size: 12px; color: #8a93a8; background: rgba(255, 255, 255, 0.06); border: 1px solid rgba(255, 255, 255, 0.12); border-radius: 980px; padding: 5px 14px; cursor: pointer; }
.refresh:hover { color: #f0f3fa; }

.addbar { display: flex; gap: 10px; margin-bottom: 8px; }
.addbar input { flex: 1; background: rgba(255, 255, 255, 0.05); border: 1px solid rgba(255, 255, 255, 0.14); border-radius: 12px; padding: 11px 16px; color: #f0f3fa; font-size: 14px; font-family: inherit; outline: none; }
.addbar input:focus { border-color: #00e0c6; }
.add-btn { background: linear-gradient(120deg, #5b8cff, #00e0c6); color: #05121f; font-weight: 700; border: none; border-radius: 12px; padding: 0 20px; font-size: 14px; cursor: pointer; white-space: nowrap; }

.sechead { font-size: 13px; font-weight: 700; letter-spacing: 0.04em; color: #8a93a8; margin: 26px 0 12px; }
.empty { color: #8a93a8; padding: 40px 0; text-align: center; font-size: 14px; }
.empty.small { padding: 20px 0; }
.empty code, .nodata code { background: rgba(255, 255, 255, 0.08); padding: 2px 8px; border-radius: 6px; color: #a9d8ff; }

.list { display: flex; flex-direction: column; gap: 8px; }
.row {
  display: flex; align-items: center; gap: 12px; border: 1px solid rgba(255, 255, 255, 0.09);
  border-radius: 14px; padding: 14px 16px; background: rgba(255, 255, 255, 0.045); cursor: pointer; transition: 0.15s;
}
.row:hover { border-color: rgba(255, 255, 255, 0.2); }
.row.open { border-color: rgba(0, 224, 198, 0.4); background: rgba(0, 224, 198, 0.05); }
.caret { color: #5c6378; width: 14px; font-size: 12px; }
.row .nm { flex: 1; font-size: 15px; font-weight: 700; }
.row .nm small { color: #5c6378; font-weight: 400; margin-left: 8px; font-size: 12px; }
.lvl { font-size: 12px; font-weight: 600; }
.temp { font-weight: 800; font-family: "SF Mono", Consolas, monospace; font-size: 18px; width: 34px; text-align: right; }
.pending { font-size: 11px; color: #8a93a8; background: rgba(255, 255, 255, 0.07); padding: 2px 9px; border-radius: 980px; }
.del { background: transparent; border: none; color: #5c6378; font-size: 20px; line-height: 1; cursor: pointer; padding: 0 4px; }
.del:hover { color: #ff5470; }

.detail { padding: 12px 2px 4px; }
.nodata { font-size: 13px; color: #8a93a8; padding: 16px; border: 1px dashed rgba(255, 255, 255, 0.14); border-radius: 12px; }

.report { border: 1px solid rgba(255, 255, 255, 0.09); border-radius: 16px; overflow: hidden; background: rgba(255, 255, 255, 0.03); }
.rep-head { padding: 16px 20px; border-bottom: 1px solid rgba(255, 255, 255, 0.09); display: flex; align-items: center; gap: 14px; }
.rep-head .name { font-size: 17px; font-weight: 700; flex: 1; }
.rep-head .name small { color: #5c6378; font-weight: 400; font-size: 13px; margin-left: 7px; }
.school { font-size: 12px; color: #8a93a8; }
.verdict { font-size: 13px; font-weight: 700; padding: 6px 14px; border-radius: 980px; color: var(--c); background: color-mix(in srgb, var(--c) 16%, transparent); }
.rep-body { display: grid; grid-template-columns: 168px 1fr; }
.ring-wrap { padding: 22px; border-right: 1px solid rgba(255, 255, 255, 0.09); text-align: center; }
.ring { width: 104px; height: 104px; border-radius: 50%; margin: 0 auto; display: flex; align-items: center; justify-content: center; position: relative; }
.ring::before { content: ""; position: absolute; inset: 11px; border-radius: 50%; background: #0c1019; }
.ring .num { position: relative; font-size: 30px; font-weight: 800; color: var(--c); }
.ring-wrap .lab { font-size: 12px; color: #8a93a8; margin-top: 12px; }
.ring-wrap .sig { font-size: 13px; color: var(--c); font-weight: 700; margin-top: 3px; }
.advice { padding: 10px 22px; }
.arow { display: flex; gap: 14px; padding: 10px 0; border-bottom: 1px solid rgba(255, 255, 255, 0.06); font-size: 14px; }
.arow:last-child { border-bottom: none; }
.arow .k { width: 64px; color: #8a93a8; flex-shrink: 0; }
.arow .vv { font-weight: 600; }
.arow.reverse .vv { color: var(--c); }
.bars { display: flex; flex-direction: column; gap: 9px; padding: 16px 22px; }
.bar { display: flex; align-items: center; gap: 12px; font-size: 13px; }
.bar.dim { opacity: 0.55; }
.bar .bl { width: 48px; color: #8a93a8; flex-shrink: 0; }
.btrk { flex: 1; height: 8px; border-radius: 980px; background: rgba(255, 255, 255, 0.06); overflow: hidden; }
.btrk i { display: block; height: 100%; border-radius: 980px; }
.bar .bv { width: 56px; text-align: right; font-weight: 700; font-family: "SF Mono", Consolas, monospace; }
.evs { display: flex; flex-wrap: wrap; gap: 10px 24px; padding: 0 22px 20px; }
.ev { font-size: 13px; }
.ev .ek { color: #5c6378; margin-right: 8px; }
.ev .evv { color: #c7cedb; font-weight: 600; }
.foot { color: #5c6378; font-size: 12.5px; margin-top: 24px; }
.foot b { color: #ffcf6b; }
</style>
