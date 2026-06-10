<script setup lang="ts">
import { ref, onMounted, computed } from "vue";
import {
  loadStocks,
  opportunityScore,
  schoolFit,
  tempColor,
  ALL_SECTORS,
  type StockRec,
} from "./useSentio";

const emit = defineEmits<{ (e: "open-report", code: string): void }>();

const stocks = ref<StockRec[]>([]);
const loading = ref(true);
const picked = ref<Set<string>>(new Set()); // 选中板块；空=全部
const manual = ref("");

async function refresh() {
  loading.value = true;
  stocks.value = await loadStocks();
  loading.value = false;
}
onMounted(refresh);

function toggle(sec: string) {
  const s = new Set(picked.value);
  s.has(sec) ? s.delete(sec) : s.add(sec);
  picked.value = s;
}

const manualCodes = computed(() =>
  manual.value
    .split(/[,，\s]+/)
    .map((x) => x.trim())
    .filter(Boolean)
);

// 扫描宇宙：板块过滤（空=全部）∪ 手动输入命中
const universe = computed(() => {
  const secOn = picked.value.size > 0;
  return stocks.value.filter((r) => {
    const bySec = !secOn || picked.value.has(r.sector);
    const byManual =
      manualCodes.value.length > 0 &&
      manualCodes.value.some((c) => r.code.includes(c) || r.name.includes(c));
    return bySec || byManual;
  });
});

// 按反向「机会分」排序，金色置顶
const ranked = computed(() =>
  [...universe.value]
    .map((r) => ({ r, score: opportunityScore(r) }))
    .sort((a, b) => b.score - a.score)
);

function whyText(r: StockRec, score: number): string {
  const f = r.breakdown.资金F ?? 50;
  if (r.temperature >= 80) return "散户狂热、情绪过热——反向降权，警惕回撤";
  if (f >= 60 && r.temperature < 65) return "情绪未过热 + 主力资金净流入——错杀修复机会";
  if (r.temperature <= 35) return "情绪冰点、被市场遗忘——价值派安全边际";
  if (score >= 55) return "资金温和、情绪不过热——成长派偏好";
  return "情绪与资金中性，结合基本面再定";
}
</script>

<template>
  <div class="sentio-view">
    <div class="inner">
      <header class="head">
        <div>
          <div class="eyebrow">智投顾 · 选股雷达</div>
          <h1>选股雷达</h1>
          <div class="lead">圈定范围 → AI 扫全网情绪 → 把机会按反向逻辑排好序</div>
        </div>
        <button class="refresh" @click="refresh">刷新</button>
      </header>

      <!-- 监控范围 -->
      <div class="scope">
        <div class="lab">监控范围 · 板块可多选（不选=全部）</div>
        <div class="chips">
          <button
            v-for="sec in ALL_SECTORS"
            :key="sec"
            class="ch"
            :class="{ on: picked.has(sec) }"
            @click="toggle(sec)"
          >
            {{ sec }}
          </button>
        </div>
        <div class="inp">
          <span class="ph">手动输入代码/名称：</span>
          <input v-model="manual" placeholder="600519，宁德，寒武纪…" />
          <span class="cnt">{{ ranked.length }} 只命中</span>
        </div>
      </div>

      <div v-if="loading" class="empty">扫描中…</div>
      <div v-else-if="!stocks.length" class="empty">
        暂无数据。请先运行采集器：<code>python data-pipeline/collect.py</code>
      </div>

      <template v-else>
        <div class="sechead">扫描机会 · 反向机会分排序（金色置顶 = 当前最优）</div>
        <div class="recs">
          <div
            v-for="({ r, score }, i) in ranked"
            :key="r.code"
            class="rec"
            :class="{ top: i === 0 }"
            @click="emit('open-report', r.code)"
          >
            <div class="badge">{{ i + 1 }}</div>
            <div class="mid">
              <div class="nm">{{ r.name }}<small>{{ r.code }} · {{ r.sector }}</small></div>
              <div class="why">{{ whyText(r, score) }}</div>
              <div class="fit">符合：{{ schoolFit(r) }}</div>
            </div>
            <div class="right">
              <div class="score">{{ score }}<small>/100</small></div>
              <div class="meta" :style="{ color: tempColor(r.temperature) }">情绪 {{ r.temperature.toFixed(0) }} · {{ r.level }}</div>
            </div>
          </div>
        </div>
        <p class="foot">
          反向逻辑：<b>不是谁涨得猛推谁</b>——散户一致狂热的降权警惕，被冷落但资金回流的才是金色机会。研究参考，非投资建议。
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
.inner { max-width: 1000px; margin: 0 auto; padding: 34px 32px 80px; }
.head { display: flex; align-items: flex-start; gap: 16px; margin-bottom: 22px; }
.eyebrow { font-size: 12px; font-weight: 600; letter-spacing: 0.06em; background: linear-gradient(120deg, #5b8cff, #00e0c6); -webkit-background-clip: text; background-clip: text; color: transparent; }
h1 { font-size: 32px; font-weight: 800; letter-spacing: -0.02em; margin: 6px 0 4px; }
.lead { color: #8a93a8; font-size: 14px; }
.refresh { margin-left: auto; font-size: 12px; color: #8a93a8; background: rgba(255, 255, 255, 0.06); border: 1px solid rgba(255, 255, 255, 0.12); border-radius: 980px; padding: 5px 14px; cursor: pointer; }
.refresh:hover { color: #f0f3fa; }

.scope { border: 1px solid rgba(255, 255, 255, 0.09); border-radius: 18px; padding: 20px; background: rgba(255, 255, 255, 0.045); margin-bottom: 8px; }
.scope .lab { font-size: 12px; color: #8a93a8; margin-bottom: 11px; }
.chips { display: flex; flex-wrap: wrap; gap: 9px; margin-bottom: 14px; }
.ch { font-size: 13px; padding: 7px 15px; border-radius: 980px; border: 1px solid rgba(255, 255, 255, 0.14); color: #8a93a8; background: transparent; cursor: pointer; transition: 0.15s; }
.ch:hover { color: #f0f3fa; }
.ch.on { border-color: transparent; background: linear-gradient(120deg, #5b8cff, #00e0c6); color: #05121f; font-weight: 600; box-shadow: 0 4px 16px rgba(0, 224, 198, 0.25); }
.inp { display: flex; align-items: center; gap: 8px; border: 1px solid rgba(255, 255, 255, 0.14); border-radius: 12px; padding: 10px 15px; }
.inp .ph { color: #5c6378; font-size: 14px; white-space: nowrap; }
.inp input { flex: 1; background: transparent; border: none; outline: none; color: #f0f3fa; font-size: 14px; font-family: inherit; }
.inp .cnt { color: #8a93a8; font-size: 12px; white-space: nowrap; }

.empty { color: #8a93a8; padding: 50px 0; text-align: center; font-size: 14px; }
.empty code { background: rgba(255, 255, 255, 0.08); padding: 2px 8px; border-radius: 6px; color: #a9d8ff; }

.sechead { font-size: 13px; font-weight: 700; letter-spacing: 0.04em; color: #8a93a8; margin: 30px 0 12px; }
.recs { display: grid; gap: 12px; }
.rec {
  display: flex; align-items: center; gap: 16px; border: 1px solid rgba(255, 255, 255, 0.09);
  border-radius: 16px; padding: 16px 18px; background: rgba(255, 255, 255, 0.045); cursor: pointer; transition: 0.15s;
}
.rec:hover { border-color: rgba(255, 255, 255, 0.2); }
.rec.top { border-color: rgba(255, 207, 107, 0.35); background: linear-gradient(100deg, rgba(255, 207, 107, 0.07), transparent 60%); }
.badge {
  flex-shrink: 0; width: 42px; height: 42px; border-radius: 13px; display: flex; align-items: center;
  justify-content: center; font-weight: 800; font-size: 18px; background: rgba(255, 255, 255, 0.07); color: #ffcf6b;
}
.rec.top .badge { background: linear-gradient(120deg, #ffcf6b, #ff9d5c); color: #3a2a00; }
.mid { flex: 1; min-width: 0; }
.nm { font-size: 16px; font-weight: 700; }
.nm small { color: #5c6378; font-weight: 400; margin-left: 7px; font-size: 12px; }
.why { font-size: 13px; color: #8a93a8; margin-top: 3px; }
.fit { font-size: 11px; color: #ffcf6b; margin-top: 5px; }
.right { text-align: right; flex-shrink: 0; }
.score { font-size: 24px; font-weight: 800; background: linear-gradient(120deg, #00e69a, #33e0ff); -webkit-background-clip: text; background-clip: text; color: transparent; line-height: 1; }
.score small { font-size: 11px; color: #5c6378; font-weight: 400; -webkit-text-fill-color: #5c6378; }
.meta { font-size: 11px; margin-top: 5px; }
.foot { color: #5c6378; font-size: 12.5px; margin-top: 18px; }
.foot b { color: #ffcf6b; }
</style>
