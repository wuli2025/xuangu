<script setup lang="ts">
import { ref, onMounted, computed, watch } from "vue";
import { storeToRefs } from "pinia";
import { useAppStore } from "../../stores/app";
import { loadStocks, tempColor, adviceOf, schoolFit, type StockRec } from "./useSentio";

const app = useAppStore();
const { sentioStock } = storeToRefs(app);

const stocks = ref<StockRec[]>([]);
const loading = ref(true);
const selected = ref<string | null>(null);

async function refresh() {
  loading.value = true;
  stocks.value = await loadStocks();
  loading.value = false;
  if (!selected.value) selected.value = sentioStock.value ?? stocks.value[0]?.code ?? null;
}
onMounted(refresh);
watch(sentioStock, (c) => {
  if (c) selected.value = c;
});

const cur = computed(() => stocks.value.find((r) => r.code === selected.value) ?? null);
const c = computed(() => (cur.value ? tempColor(cur.value.temperature) : "#8a93a8"));
const adv = computed(() => (cur.value ? adviceOf(cur.value) : null));
const ringPct = computed(() => Math.max(0, Math.min(100, cur.value?.temperature ?? 0)));
const evidence = computed(() => (cur.value ? Object.entries(cur.value.evidence) : []));
</script>

<template>
  <div class="sentio-view">
    <div class="inner">
      <header class="head">
        <div>
          <div class="eyebrow">SENTIO · 个股报告</div>
          <h1>个股报告</h1>
        </div>
        <select v-model="selected" class="picker">
          <option v-for="r in stocks" :key="r.code" :value="r.code">
            {{ r.name }} {{ r.code }}
          </option>
        </select>
      </header>

      <div v-if="loading" class="empty">载入…</div>
      <div v-else-if="!cur" class="empty">
        暂无数据。请先运行采集器：<code>python data-pipeline/collect.py</code>
      </div>

      <template v-else>
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
              <div class="row"><span class="k">结论</span><span class="vv">{{ adv?.action }}</span></div>
              <div class="row"><span class="k">仓位</span><span class="vv">{{ adv?.position }}</span></div>
              <div class="row"><span class="k">止损</span><span class="vv">{{ adv?.stop }}</span></div>
              <div class="row"><span class="k">止盈</span><span class="vv">{{ adv?.target }}</span></div>
              <div class="row reverse"><span class="k">反向提示</span><span class="vv">{{ cur.signal }}</span></div>
            </div>
          </div>
        </div>

        <!-- 分维度拆解 -->
        <div class="sechead">情绪温度拆解</div>
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
            <span class="bl">情感 S</span>
            <span class="btrk"></span>
            <span class="bv">— 待接</span>
          </div>
        </div>

        <!-- 证据 -->
        <div class="sechead">情报依据</div>
        <div class="evs">
          <div v-for="[k, v] in evidence" :key="k" class="ev">
            <span class="ek">{{ k }}</span><span class="evv">{{ v }}</span>
          </div>
        </div>

        <p class="foot">
          温度 = 0.40·热度 + 0.35·资金（情感待接入）。情绪为<b>概率性反向信号</b>，会出错；研究参考，不构成投资建议，风险自负。
        </p>
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
.inner { max-width: 920px; margin: 0 auto; padding: 34px 32px 80px; }
.head { display: flex; align-items: flex-end; gap: 16px; margin-bottom: 24px; }
.eyebrow { font-size: 12px; font-weight: 600; letter-spacing: 0.06em; background: linear-gradient(120deg, #5b8cff, #00e0c6); -webkit-background-clip: text; background-clip: text; color: transparent; }
h1 { font-size: 32px; font-weight: 800; letter-spacing: -0.02em; margin: 6px 0 0; }
.picker {
  margin-left: auto; background: rgba(255, 255, 255, 0.06); border: 1px solid rgba(255, 255, 255, 0.14);
  color: #f0f3fa; border-radius: 10px; padding: 8px 14px; font-size: 14px; font-family: inherit; cursor: pointer;
}
.picker option { background: #0c1019; }
.empty { color: #8a93a8; padding: 60px 0; text-align: center; font-size: 14px; }
.empty code { background: rgba(255, 255, 255, 0.08); padding: 2px 8px; border-radius: 6px; color: #a9d8ff; }

.report { border: 1px solid rgba(255, 255, 255, 0.09); border-radius: 18px; overflow: hidden; background: rgba(255, 255, 255, 0.045); }
.rep-head { padding: 18px 22px; border-bottom: 1px solid rgba(255, 255, 255, 0.09); display: flex; align-items: center; gap: 14px; }
.rep-head .name { font-size: 19px; font-weight: 700; flex: 1; }
.rep-head .name small { color: #5c6378; font-weight: 400; font-size: 13px; margin-left: 7px; }
.school { font-size: 12px; color: #8a93a8; }
.verdict { font-size: 13px; font-weight: 700; padding: 6px 14px; border-radius: 980px; color: var(--c); background: color-mix(in srgb, var(--c) 16%, transparent); }
.rep-body { display: grid; grid-template-columns: 170px 1fr; }
.ring-wrap { padding: 24px; border-right: 1px solid rgba(255, 255, 255, 0.09); text-align: center; }
.ring { width: 110px; height: 110px; border-radius: 50%; margin: 0 auto; display: flex; align-items: center; justify-content: center; position: relative; }
.ring::before { content: ""; position: absolute; inset: 11px; border-radius: 50%; background: #0c1019; }
.ring .num { position: relative; font-size: 32px; font-weight: 800; color: var(--c); }
.ring-wrap .lab { font-size: 12px; color: #8a93a8; margin-top: 12px; }
.ring-wrap .sig { font-size: 13px; color: var(--c); font-weight: 700; margin-top: 3px; }
.advice { padding: 12px 22px; }
.advice .row { display: flex; gap: 14px; padding: 11px 0; border-bottom: 1px solid rgba(255, 255, 255, 0.06); font-size: 14px; }
.advice .row:last-child { border-bottom: none; }
.advice .row .k { width: 64px; color: #8a93a8; flex-shrink: 0; }
.advice .row .vv { font-weight: 600; }
.advice .row.reverse .vv { color: var(--c); }

.sechead { font-size: 13px; font-weight: 700; letter-spacing: 0.04em; color: #8a93a8; margin: 32px 0 14px; }
.bars { display: flex; flex-direction: column; gap: 10px; max-width: 560px; }
.bar { display: flex; align-items: center; gap: 12px; font-size: 13px; }
.bar.dim { opacity: 0.55; }
.bar .bl { width: 48px; color: #8a93a8; flex-shrink: 0; }
.btrk { flex: 1; height: 8px; border-radius: 980px; background: rgba(255, 255, 255, 0.06); overflow: hidden; }
.btrk i { display: block; height: 100%; border-radius: 980px; }
.bar .bv { width: 56px; text-align: right; font-weight: 700; font-family: "SF Mono", Consolas, monospace; }

.evs { display: flex; flex-wrap: wrap; gap: 10px 24px; }
.ev { font-size: 13px; }
.ev .ek { color: #5c6378; margin-right: 8px; }
.ev .evv { color: #c7cedb; font-weight: 600; }
.foot { color: #5c6378; font-size: 12.5px; margin-top: 26px; }
.foot b { color: #ffcf6b; }
</style>
