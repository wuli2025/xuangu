<script setup lang="ts">
import { ref, onMounted, computed } from "vue";
import { loadBoard, tempColor, levelColor, type Board } from "./useSentio";

const emit = defineEmits<{ (e: "open-report", code: string): void }>();

const board = ref<Board | null>(null);
const loading = ref(true);

async function refresh() {
  loading.value = true;
  board.value = await loadBoard();
  loading.value = false;
}
onMounted(refresh);

const mt = computed(() => board.value?.market_temp ?? 0);
const mc = computed(() => tempColor(mt.value));
const bw = computed(() => board.value?.breadth ?? {});
const ranked = computed(() => board.value?.ranked ?? []);
const updated = computed(() =>
  board.value?.updated_at ? board.value.updated_at.replace("T", " ").slice(0, 16) : ""
);
</script>

<template>
  <div class="sentio-view">
    <div class="inner">
      <header class="head">
        <div>
          <div class="eyebrow">SENTIO · AI 智能选股舆情终端</div>
          <h1>舆情看板</h1>
        </div>
        <div class="live" v-if="board">数据 {{ updated }} · 点任意行生成报告</div>
        <button class="refresh" @click="refresh">刷新</button>
      </header>

      <div v-if="loading" class="empty">载入采集数据…</div>
      <div v-else-if="!board" class="empty">
        暂无数据。请先运行采集器：<code>python data-pipeline/collect.py</code>
      </div>

      <template v-else>
        <!-- 市场总览 -->
        <div class="dash">
          <div class="gauge" :style="{ '--mc': mc }">
            <div class="k">市场情绪温度（自选池均值）</div>
            <div class="big">{{ mt.toFixed(0) }}</div>
            <div class="tag">{{ board.market_signal }}</div>
          </div>
          <div class="stat">
            <div class="k">涨跌家数（沪深）</div>
            <div class="v">
              <span class="up">{{ bw.up ?? "—" }}</span> /
              <span class="down">{{ bw.down ?? "—" }}</span>
            </div>
            <div class="s">上涨占比 {{ bw.up_ratio ?? "—" }}% · 平 {{ bw.flat ?? "—" }}</div>
          </div>
          <div class="stat">
            <div class="k">情绪反转预警</div>
            <div class="v down">{{ board.reversal_alerts }} 只</div>
            <div class="s">过热 / 偏热 · 散户偏一致</div>
          </div>
          <div class="stat">
            <div class="k">大盘指数</div>
            <div class="idx">
              <span v-for="i in bw.indices" :key="i.name">
                {{ i.name }}
                <b :class="i.chg >= 0 ? 'up' : 'down'">{{ i.chg >= 0 ? "+" : "" }}{{ i.chg.toFixed(2) }}%</b>
              </span>
              <span v-if="!bw.indices?.length" class="s">—</span>
            </div>
          </div>
        </div>

        <!-- 全网热度榜 -->
        <div class="sechead">🔥 全网热度榜 · 按情绪温度排序</div>
        <div class="hotlist">
          <div class="hot-h">
            <span>标的</span><span>情绪温度</span>
          </div>
          <div
            v-for="(r, i) in ranked"
            :key="r.code"
            class="hrow"
            @click="emit('open-report', r.code)"
          >
            <span class="rank">{{ i + 1 }}</span>
            <span class="nm">{{ r.name }}<small>{{ r.code }} · {{ r.sector }}</small></span>
            <span class="bull" :style="{ color: levelColor(r.level), background: levelColor(r.level) + '22' }">{{ r.level }}</span>
            <span class="temp" :style="{ color: tempColor(r.temperature) }">{{ r.temperature.toFixed(0) }}</span>
            <span class="go">›</span>
          </div>
        </div>
        <p class="foot">情绪是<b>反向指标</b>：≥80 过热警惕回撤，≤20 冰点可关注。研究参考，非投资建议。</p>
      </template>
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
.head { display: flex; align-items: flex-end; gap: 16px; margin-bottom: 8px; }
.eyebrow {
  font-size: 12px; font-weight: 600; letter-spacing: 0.06em;
  background: linear-gradient(120deg, #5b8cff, #00e0c6); -webkit-background-clip: text; background-clip: text; color: transparent;
}
h1 { font-size: 32px; font-weight: 800; letter-spacing: -0.02em; margin: 6px 0 0; }
.live { margin-left: auto; font-size: 12px; color: #00e69a; display: flex; align-items: center; gap: 7px; }
.live::before { content: ""; width: 7px; height: 7px; border-radius: 50%; background: #00e69a; box-shadow: 0 0 8px #00e69a; }
.refresh {
  font-size: 12px; color: #8a93a8; background: rgba(255, 255, 255, 0.06);
  border: 1px solid rgba(255, 255, 255, 0.12); border-radius: 980px; padding: 5px 14px; cursor: pointer;
}
.refresh:hover { color: #f0f3fa; }
.empty { color: #8a93a8; padding: 60px 0; text-align: center; font-size: 14px; }
.empty code { background: rgba(255, 255, 255, 0.08); padding: 2px 8px; border-radius: 6px; color: #a9d8ff; }

.dash { display: flex; gap: 16px; flex-wrap: wrap; margin: 24px 0 8px; }
.gauge {
  flex: 1.4; min-width: 240px; border: 1px solid rgba(255, 255, 255, 0.09); border-radius: 20px;
  padding: 22px; background: rgba(255, 255, 255, 0.045); position: relative; overflow: hidden;
}
.gauge::after {
  content: ""; position: absolute; right: -30px; top: -30px; width: 140px; height: 140px;
  border-radius: 50%; background: var(--mc); opacity: 0.16; filter: blur(26px);
}
.gauge .k { font-size: 12px; color: #8a93a8; }
.gauge .big { font-size: 60px; font-weight: 800; letter-spacing: -0.03em; line-height: 1; margin: 6px 0; color: var(--mc); }
.gauge .tag { font-size: 13px; color: var(--mc); font-weight: 700; }
.stat {
  flex: 1; min-width: 150px; border: 1px solid rgba(255, 255, 255, 0.09); border-radius: 20px;
  padding: 18px 20px; background: rgba(255, 255, 255, 0.045);
}
.stat .k { font-size: 12px; color: #8a93a8; }
.stat .v { font-size: 27px; font-weight: 700; margin-top: 6px; }
.stat .s { font-size: 11px; color: #5c6378; margin-top: 3px; }
.stat .idx { font-size: 13px; margin-top: 8px; line-height: 1.7; }
.stat .idx span { display: block; }
.up { color: #00e69a; }
.down { color: #ff5470; }

.sechead {
  font-size: 13px; font-weight: 700; letter-spacing: 0.04em; color: #8a93a8; margin: 34px 0 12px;
}
.hotlist {
  border: 1px solid rgba(255, 255, 255, 0.09); border-radius: 18px; overflow: hidden; background: rgba(255, 255, 255, 0.045);
}
.hot-h {
  padding: 11px 18px; font-size: 12px; color: #8a93a8; border-bottom: 1px solid rgba(255, 255, 255, 0.09);
  display: flex; justify-content: space-between;
}
.hrow {
  display: flex; align-items: center; gap: 12px; padding: 14px 18px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.06); font-size: 14px; cursor: pointer; transition: background 0.15s;
}
.hrow:last-child { border-bottom: none; }
.hrow:hover { background: rgba(255, 255, 255, 0.04); }
.hrow .rank {
  width: 22px; height: 22px; border-radius: 7px; background: rgba(255, 255, 255, 0.07);
  display: flex; align-items: center; justify-content: center; font-size: 12px; font-weight: 700; color: #ffcf6b; flex-shrink: 0;
}
.hrow .nm { flex: 1; font-weight: 600; }
.hrow .nm small { color: #5c6378; font-weight: 400; margin-left: 7px; font-size: 12px; }
.bull { font-size: 11px; padding: 2px 9px; border-radius: 980px; font-weight: 600; }
.temp { font-weight: 800; font-family: "SF Mono", Consolas, monospace; width: 40px; text-align: right; font-size: 18px; }
.go { color: #5c6378; font-size: 18px; width: 14px; text-align: center; }
.foot { color: #5c6378; font-size: 12.5px; margin-top: 18px; }
.foot b { color: #ffcf6b; }
</style>
