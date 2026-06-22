<script setup lang="ts">
import { ref, onMounted, computed, onUnmounted } from "vue";
import {
  loadStrategy,
  scoreColor,
  tempColor,
  type Strategy,
  type Pick,
} from "./useSentio";
import { useCheck } from "./useCheck";

const emit = defineEmits<{ (e: "open-report", code: string): void }>();

const strat = ref<Strategy | null>(null);
const loading = ref(true);
const showRanked = ref(false);

const check = useCheck();
let offDone: (() => void) | null = null;

async function refresh() {
  loading.value = true;
  strat.value = await loadStrategy();
  loading.value = false;
}
async function runNow() {
  await check.start();
}
onMounted(() => {
  refresh();
  offDone = check.onDone((d) => {
    if (d.ok) refresh();
  });
});
onUnmounted(() => offDone?.());

const bt = computed(() => strat.value?.backtest ?? null);
const updated = computed(() =>
  strat.value?.updated_at ? strat.value.updated_at.replace("T", " ").slice(0, 16) : ""
);

// 回测权益曲线 → SVG 折线（strat vs bench）
const W = 680;
const H = 150;
const PAD = 6;
function curvePath(key: "strat" | "bench"): string {
  const c = bt.value?.curve ?? [];
  if (c.length < 2) return "";
  const vals = c.flatMap((p) => [p.strat, p.bench]);
  const min = Math.min(...vals);
  const max = Math.max(...vals);
  const span = max - min || 1;
  const n = c.length;
  return c
    .map((p, i) => {
      const x = PAD + (i / (n - 1)) * (W - 2 * PAD);
      const y = H - PAD - ((p[key] - min) / span) * (H - 2 * PAD);
      return `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
}
const stratPath = computed(() => curvePath("strat"));
const benchPath = computed(() => curvePath("bench"));

// 稳健性矩阵：行=动量回看(月)，列=持仓数
const sensLookbacks = computed(() =>
  [...new Set((bt.value?.sensitivity ?? []).map((s) => s.lookback))].sort((a, b) => a - b)
);
const sensTopks = computed(() =>
  [...new Set((bt.value?.sensitivity ?? []).map((s) => s.topk))].sort((a, b) => a - b)
);
function sensVal(lb: number, tk: number): number | null {
  const hit = (bt.value?.sensitivity ?? []).find((s) => s.lookback === lb && s.topk === tk);
  return hit ? hit.cagr : null;
}
function sensColor(v: number | null): string {
  if (v == null) return "rgba(255,255,255,0.03)";
  // 0% 灰 → 越高越绿
  const t = Math.max(0, Math.min(1, v / 80));
  return `rgba(0, 230, 154, ${(0.08 + t * 0.32).toFixed(2)})`;
}

const radarKeys = ["动量", "趋势", "资金", "低波", "情绪"] as const;
function radarVal(p: Pick, k: (typeof radarKeys)[number]): number {
  return (p.radar as any)[k] ?? 50;
}

function openReport(code: string) {
  emit("open-report", code);
}
</script>

<template>
  <div class="sentio-view">
    <div class="inner">
      <header class="head">
        <div>
          <div class="eyebrow">智投顾 · 选股达人</div>
          <h1>建议策略</h1>
          <div class="lead">多因子达人评分 → 交易计划 → 组合配置 → 历史回测，纪律化闭环</div>
        </div>
        <button class="check" :disabled="check.running.value" @click="runNow">
          <span class="dot" :class="{ spin: check.running.value }"></span>
          {{ check.running.value ? "计算中…" : "立即检查" }}
        </button>
      </header>

      <div v-if="check.running.value || check.ok.value === false" class="progress">
        <div class="ptop">
          <span class="plabel">{{ check.running.value ? "采集舆情 → 多因子打分 → 月度回测" : "检查未完成" }}</span>
          <span class="ppct">{{ check.pct.value }}%</span>
        </div>
        <div class="ptrack"><i :style="{ width: check.pct.value + '%' }"></i></div>
        <div class="plog">{{ check.lines.value[check.lines.value.length - 1] || check.lastMsg.value }}</div>
      </div>

      <div v-if="loading" class="empty">载入策略数据…</div>
      <div v-else-if="!strat" class="empty">
        暂无策略。点右上「立即检查」运行采集与分析，或先跑
        <code>python data-pipeline/run_all.py</code>
      </div>

      <template v-else>
        <!-- 市场态势 + 组合预期 -->
        <div class="topgrid">
          <div class="card stance">
            <div class="k">市场态势 · 建议仓位</div>
            <div class="cashrow">
              <div class="cash">
                <div class="cnum">{{ 100 - strat.market.cash_pct }}<small>%</small></div>
                <div class="clab">建议持仓</div>
              </div>
              <div class="cash dim">
                <div class="cnum">{{ strat.market.cash_pct }}<small>%</small></div>
                <div class="clab">现金缓冲</div>
              </div>
            </div>
            <div class="stancenote" v-if="strat.market.market_temp != null">
              市场情绪 {{ strat.market.market_temp?.toFixed(0) }}（{{ strat.market.market_level }}）· {{ strat.market.stance }}
            </div>
            <div class="stancenote" v-else>{{ strat.market.stance }}</div>
          </div>

          <div class="card exp" v-if="strat.expectation">
            <div class="k">组合月度预期（历史分布外推，非承诺）</div>
            <div class="expnum">
              <span class="emain">{{ strat.expectation.base_monthly > 0 ? "+" : "" }}{{ strat.expectation.base_monthly }}<small>%</small></span>
              <span class="erange">区间 {{ strat.expectation.range_low }}% ~ {{ strat.expectation.range_high }}%</span>
            </div>
            <div class="expnote">{{ strat.expectation.note }}</div>
          </div>
        </div>

        <!-- 目标收益闭环：诚实engage「月化10%」诉求 -->
        <template v-if="strat.target && strat.modes">
          <div class="sechead">🎯 目标收益可行性 · 月化 {{ strat.target.target_monthly }}%</div>
          <div class="target">
            <div class="tverdict">{{ strat.target.verdict }}</div>

            <!-- 目标达成配置：历史上够到月化目标的最激进打法 + 代价 -->
            <div v-if="strat.target.achiever" class="achiever" :class="{ ok: strat.target.achiever.achieved }">
              <div class="ahead">
                <span class="atitle">{{ strat.target.achiever.achieved ? "🔥 历史达标配置" : "⚠ 历史最接近配置" }}</span>
                <span class="aconfig">{{ strat.target.achiever.config_text }}</span>
              </div>
              <div class="agrid">
                <div class="ag"><div class="av up">{{ strat.target.achiever.monthly_mean }}%</div><div class="al">历史月均</div></div>
                <div class="ag"><div class="av up">{{ strat.target.achiever.p_hit }}%</div><div class="al">月份≥{{ strat.target.target_monthly }}%</div></div>
                <div class="ag"><div class="av">{{ strat.target.achiever.win_rate }}%</div><div class="al">胜率</div></div>
                <div class="ag"><div class="av down">{{ strat.target.achiever.max_drawdown }}%</div><div class="al">最大回撤(代价)</div></div>
                <div class="ag"><div class="av down">{{ strat.target.achiever.p_lose }}%</div><div class="al">月份≤-{{ strat.target.target_monthly }}%</div></div>
                <div class="ag"><div class="av">{{ strat.target.achiever.sharpe }}</div><div class="al">夏普</div></div>
              </div>
            </div>

            <div class="tbars">
              <div class="tb">
                <div class="tbtop"><span>历史单月达成 ≥{{ strat.target.target_monthly }}% 的频率</span><b class="up">{{ strat.target.p_hit }}%</b></div>
                <div class="tbtrk"><i class="up" :style="{ width: strat.target.p_hit + '%' }"></i></div>
              </div>
              <div class="tb">
                <div class="tbtop"><span>历史单月巨亏 ≤-{{ strat.target.target_monthly }}% 的频率（代价）</span><b class="down">{{ strat.target.p_lose }}%</b></div>
                <div class="tbtrk"><i class="down" :style="{ width: strat.target.p_lose + '%' }"></i></div>
              </div>
            </div>
            <div class="tnote">{{ strat.target.honest_note }}</div>
          </div>

          <div class="modes">
            <div v-for="m in strat.modes" :key="m.key" class="mode" :class="{ hot: m.key === '进取' }">
              <div class="mkey">{{ m.key }}<span v-if="m.key === '进取'" class="mtag">冲目标</span></div>
              <div class="mdesc">{{ m.desc }}</div>
              <div class="mmain"><span class="mm">{{ m.monthly_mean > 0 ? "+" : "" }}{{ m.monthly_mean }}%</span><small>历史月均</small></div>
              <div class="mstats">
                <span>年化 <b>{{ m.cagr }}%</b></span>
                <span>胜率 <b>{{ m.win_rate }}%</b></span>
                <span>回撤 <b class="down">{{ m.max_drawdown }}%</b></span>
                <span>夏普 <b>{{ m.sharpe }}</b></span>
                <span>达 {{ strat.target.target_monthly }}% <b class="up">{{ m.p_hit }}%</b>月</span>
                <span>持仓 <b>{{ m.topk }}</b>只</span>
              </div>
            </div>
          </div>
        </template>

        <!-- 核心持仓 -->
        <div class="sechead">⭐ 核心持仓建议 · 达人评分 Top {{ strat.picks.length }}</div>
        <div class="picks">
          <div v-for="p in strat.picks" :key="p.code" class="pick" @click="openReport(p.code)">
            <div class="pleft">
              <div class="pring" :style="{ background: `conic-gradient(${scoreColor(p.score)} 0 ${p.score}%, rgba(255,255,255,.08) ${p.score}% 100%)` }">
                <div class="pnum" :style="{ color: scoreColor(p.score) }">{{ p.score }}</div>
              </div>
              <div class="pscore-lab">达人评分</div>
            </div>
            <div class="pmid">
              <div class="pnm">
                {{ p.name }}<small>{{ p.code }} · {{ p.sector }}</small>
                <span class="weight">建议仓位 {{ p.weight }}%</span>
              </div>
              <div class="preason">{{ p.reason }}</div>
              <!-- 五因子雷达条 -->
              <div class="radar">
                <div v-for="k in radarKeys" :key="k" class="rbar">
                  <span class="rk">{{ k }}</span>
                  <span class="rtrk"><i :style="{ width: radarVal(p, k) + '%', background: scoreColor(radarVal(p, k)) }"></i></span>
                  <span class="rv">{{ radarVal(p, k) }}</span>
                </div>
              </div>
            </div>
            <div class="pplan">
              <div class="prow"><span class="pk">参考买入</span><span class="pv">¥{{ p.entry }}</span></div>
              <div class="prow"><span class="pk">止损</span><span class="pv down">¥{{ p.stop }} <small>{{ p.stop_pct }}%</small></span></div>
              <div class="prow"><span class="pk">目标</span><span class="pv up">¥{{ p.target }} <small>+{{ p.target_pct }}%</small></span></div>
              <div class="prow"><span class="pk">情绪/RSI</span><span class="pv" :style="{ color: tempColor(p.temp) }">{{ p.temp.toFixed(0) }} / {{ p.rsi.toFixed(0) }}</span></div>
            </div>
          </div>
        </div>
        <p class="hint">仓位按「单笔风险≤2% + ATR/8% 止损」等风险测算，盈亏比≥3:1。点卡片看个股报告。</p>

        <!-- 回测 -->
        <template v-if="bt">
          <div class="sechead">📈 策略回测 · 月度再平衡（{{ bt.months }} 个月，净于成本）</div>
          <div class="btwrap">
            <div class="chart">
              <svg :viewBox="`0 0 ${W} ${H}`" preserveAspectRatio="none" class="svg">
                <path :d="benchPath" class="line bench" />
                <path :d="stratPath" class="line strat" />
              </svg>
              <div class="legend">
                <span class="lg"><i class="ls strat"></i>本策略 +{{ bt.total_return }}%</span>
                <span class="lg"><i class="ls bench"></i>等权基准 +{{ bt.bench_total }}%</span>
                <span class="lg dim">{{ bt.curve[0]?.date }} → {{ bt.curve[bt.curve.length - 1]?.date }}</span>
              </div>
            </div>
            <div class="metrics">
              <div class="m"><div class="mv" :style="{ color: bt.cagr >= 0 ? '#00e69a' : '#ff5470' }">{{ bt.cagr }}%</div><div class="ml">年化(CAGR)</div></div>
              <div class="m"><div class="mv">{{ bt.win_rate }}%</div><div class="ml">月胜率</div></div>
              <div class="m"><div class="mv down">{{ bt.max_drawdown }}%</div><div class="ml">最大回撤</div></div>
              <div class="m"><div class="mv">{{ bt.sharpe }}</div><div class="ml">夏普</div></div>
              <div class="m"><div class="mv">{{ bt.monthly_mean }}%</div><div class="ml">月均收益</div></div>
              <div class="m"><div class="mv">{{ bt.vol_ann }}%</div><div class="ml">年化波动</div></div>
            </div>
          </div>
          <!-- 稳健性矩阵：多组参数证明非过拟合单一配置 -->
          <div v-if="bt.sensitivity && bt.sensitivity.length" class="sens">
            <div class="senshead">参数稳健性 · 年化(CAGR)随「动量回看 × 持仓数」变化（普遍跑赢=非过拟合）</div>
            <div class="sensgrid">
              <div class="sg corner"></div>
              <div v-for="tk in sensTopks" :key="'h' + tk" class="sg colh">持{{ tk }}只</div>
              <template v-for="lb in sensLookbacks" :key="'r' + lb">
                <div class="sg rowh">{{ lb }}月</div>
                <div v-for="tk in sensTopks" :key="lb + '-' + tk" class="sg cell"
                  :style="{ background: sensColor(sensVal(lb, tk)) }">
                  {{ sensVal(lb, tk) != null ? sensVal(lb, tk) + "%" : "—" }}
                </div>
              </template>
            </div>
          </div>

          <p class="caveat">
            ⚠ 诚实提示：本回测宇宙是<b>当下龙头精选</b>，存在「事后选择偏差」，绝对收益会被高估；
            更应看的是<b>相对基准的超额</b>（{{ bt.total_return }}% vs {{ bt.bench_total }}%）与<b>回撤/夏普</b>。
            参数：{{ Object.entries(bt.params).map(([k, v]) => k + ' ' + v).join(' · ') }}。回测不代表未来。
          </p>
        </template>

        <!-- 全市场评分榜 -->
        <div class="sechead clickable" @click="showRanked = !showRanked">
          {{ showRanked ? "▾" : "▸" }} 全宇宙达人评分榜（{{ strat.ranked.length }} 只）
        </div>
        <div v-if="showRanked" class="ranked">
          <div class="rhead"><span>#</span><span>标的</span><span>达人评分</span><span>60日动量</span><span>RSI</span><span>情绪</span></div>
          <div v-for="(r, i) in strat.ranked" :key="r.code" class="rrow" @click="openReport(r.code)">
            <span class="ri">{{ i + 1 }}</span>
            <span class="rn">{{ r.name }}<small>{{ r.code }} · {{ r.sector }}</small></span>
            <span class="rs" :style="{ color: scoreColor(r.score) }">{{ r.score }}</span>
            <span :class="(r.mom60 ?? 0) >= 0 ? 'up' : 'down'">{{ r.mom60 != null ? (r.mom60 >= 0 ? "+" : "") + r.mom60 + "%" : "—" }}</span>
            <span :class="r.rsi > 80 ? 'down' : ''">{{ r.rsi.toFixed(0) }}</span>
            <span :style="{ color: tempColor(r.temp) }">{{ r.temp.toFixed(0) }}</span>
          </div>
        </div>

        <p class="foot">{{ strat.disclaimer }}</p>
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
.head { display: flex; align-items: flex-start; gap: 16px; margin-bottom: 6px; }
.eyebrow { font-size: 12px; font-weight: 600; letter-spacing: 0.06em; background: linear-gradient(120deg, #5b8cff, #00e0c6); -webkit-background-clip: text; background-clip: text; color: transparent; }
h1 { font-size: 32px; font-weight: 800; letter-spacing: -0.02em; margin: 6px 0 4px; }
.lead { color: #8a93a8; font-size: 14px; }

.check {
  margin-left: auto; display: inline-flex; align-items: center; gap: 8px;
  font-size: 13px; font-weight: 700; color: #05121f;
  background: linear-gradient(120deg, #5b8cff, #00e0c6); border: none;
  border-radius: 980px; padding: 9px 20px; cursor: pointer; white-space: nowrap;
  box-shadow: 0 6px 20px rgba(0, 224, 198, 0.28); transition: 0.15s;
}
.check:hover { filter: brightness(1.06); transform: translateY(-1px); }
.check:disabled { opacity: 0.7; cursor: default; transform: none; }
.check .dot { width: 8px; height: 8px; border-radius: 50%; background: #05121f; }
.check .dot.spin { border: 2px solid rgba(5, 18, 31, 0.35); border-top-color: #05121f; background: transparent; animation: spin 0.7s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }

.progress { border: 1px solid rgba(0, 224, 198, 0.25); border-radius: 14px; padding: 14px 18px; background: rgba(0, 224, 198, 0.05); margin: 18px 0 6px; }
.ptop { display: flex; justify-content: space-between; font-size: 12px; color: #8a93a8; margin-bottom: 8px; }
.ptop .ppct { color: #00e0c6; font-weight: 700; font-family: "SF Mono", Consolas, monospace; }
.ptrack { height: 6px; border-radius: 980px; background: rgba(255, 255, 255, 0.08); overflow: hidden; }
.ptrack i { display: block; height: 100%; border-radius: 980px; background: linear-gradient(90deg, #5b8cff, #00e0c6); transition: width 0.4s ease; }
.plog { margin-top: 9px; font-size: 11.5px; color: #6b7384; font-family: "SF Mono", Consolas, monospace; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

.empty { color: #8a93a8; padding: 50px 0; text-align: center; font-size: 14px; }
.empty code { background: rgba(255, 255, 255, 0.08); padding: 2px 8px; border-radius: 6px; color: #a9d8ff; }

.topgrid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin: 24px 0 8px; }
.card { border: 1px solid rgba(255, 255, 255, 0.09); border-radius: 18px; padding: 20px; background: rgba(255, 255, 255, 0.045); }
.card .k { font-size: 12px; color: #8a93a8; margin-bottom: 14px; }
.cashrow { display: flex; gap: 24px; }
.cash .cnum { font-size: 38px; font-weight: 800; line-height: 1; color: #00e69a; }
.cash .cnum small { font-size: 16px; font-weight: 600; }
.cash.dim .cnum { color: #5c6378; }
.cash .clab { font-size: 11px; color: #8a93a8; margin-top: 5px; }
.stancenote { font-size: 12.5px; color: #c7cedb; margin-top: 14px; line-height: 1.6; }
.exp .expnum { display: flex; align-items: baseline; gap: 14px; flex-wrap: wrap; }
.emain { font-size: 38px; font-weight: 800; line-height: 1; background: linear-gradient(120deg, #00e69a, #33e0ff); -webkit-background-clip: text; background-clip: text; color: transparent; }
.emain small { font-size: 16px; -webkit-text-fill-color: #00e69a; }
.erange { font-size: 13px; color: #8a93a8; }
.expnote { font-size: 11.5px; color: #6b7384; margin-top: 14px; line-height: 1.6; }

.sechead { font-size: 13px; font-weight: 700; letter-spacing: 0.04em; color: #8a93a8; margin: 34px 0 14px; }
.sechead.clickable { cursor: pointer; user-select: none; }
.sechead.clickable:hover { color: #c7cedb; }

.target { border: 1px solid rgba(255, 207, 107, 0.25); border-radius: 18px; padding: 20px; background: rgba(255, 207, 107, 0.04); }
.tverdict { font-size: 14px; color: #f0f3fa; font-weight: 600; line-height: 1.7; }
.achiever { margin: 16px 0; padding: 16px 18px; border-radius: 14px; border: 1px solid rgba(255, 84, 112, 0.3); background: rgba(255, 84, 112, 0.06); }
.achiever.ok { border-color: rgba(255, 207, 107, 0.4); background: linear-gradient(150deg, rgba(255, 207, 107, 0.1), rgba(255, 84, 112, 0.05) 80%); }
.ahead { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; margin-bottom: 14px; }
.atitle { font-size: 14px; font-weight: 800; }
.aconfig { font-size: 12px; font-weight: 700; color: #ffcf6b; background: rgba(255, 207, 107, 0.12); padding: 4px 12px; border-radius: 980px; font-family: "SF Mono", Consolas, monospace; }
.agrid { display: grid; grid-template-columns: repeat(6, 1fr); gap: 10px; }
.ag { text-align: center; }
.ag .av { font-size: 19px; font-weight: 800; font-family: "SF Mono", Consolas, monospace; }
.ag .av.up { color: #00e69a; } .ag .av.down { color: #ff5470; }
.ag .al { font-size: 10.5px; color: #8a93a8; margin-top: 4px; line-height: 1.3; }
.tbars { display: flex; flex-direction: column; gap: 12px; margin: 16px 0; }
.tb .tbtop { display: flex; justify-content: space-between; font-size: 12.5px; color: #8a93a8; margin-bottom: 6px; }
.tb .tbtop b { font-family: "SF Mono", Consolas, monospace; }
.tbtrk { height: 8px; border-radius: 980px; background: rgba(255, 255, 255, 0.07); overflow: hidden; }
.tbtrk i { display: block; height: 100%; border-radius: 980px; }
.tbtrk i.up { background: linear-gradient(90deg, #00e69a, #33e0ff); }
.tbtrk i.down { background: linear-gradient(90deg, #ff5470, #ff8a5c); }
.tnote { font-size: 11.5px; color: #8a93a8; line-height: 1.7; margin-top: 6px; padding-top: 12px; border-top: 1px solid rgba(255, 255, 255, 0.08); }

.modes { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin-top: 12px; }
.mode { border: 1px solid rgba(255, 255, 255, 0.09); border-radius: 16px; padding: 16px 18px; background: rgba(255, 255, 255, 0.04); }
.mode.hot { border-color: rgba(255, 207, 107, 0.4); background: linear-gradient(150deg, rgba(255, 207, 107, 0.08), transparent 70%); }
.mkey { font-size: 16px; font-weight: 800; display: flex; align-items: center; gap: 8px; }
.mtag { font-size: 10px; font-weight: 700; color: #3a2a00; background: linear-gradient(120deg, #ffcf6b, #ff9d5c); padding: 2px 8px; border-radius: 980px; }
.mdesc { font-size: 11.5px; color: #8a93a8; margin: 6px 0 12px; min-height: 30px; line-height: 1.5; }
.mmain { display: flex; align-items: baseline; gap: 7px; }
.mmain .mm { font-size: 26px; font-weight: 800; font-family: "SF Mono", Consolas, monospace; background: linear-gradient(120deg, #00e69a, #33e0ff); -webkit-background-clip: text; background-clip: text; color: transparent; }
.mmain small { font-size: 11px; color: #8a93a8; }
.mstats { display: grid; grid-template-columns: 1fr 1fr; gap: 5px 12px; margin-top: 12px; font-size: 11.5px; color: #8a93a8; }
.mstats b { color: #d6f5ea; font-family: "SF Mono", Consolas, monospace; font-weight: 700; }
.mstats b.up { color: #00e69a; } .mstats b.down { color: #ff5470; }

.picks { display: grid; gap: 13px; }
.pick { display: grid; grid-template-columns: 96px 1fr 200px; gap: 18px; align-items: center;
  border: 1px solid rgba(255, 255, 255, 0.09); border-radius: 18px; padding: 18px 20px;
  background: rgba(255, 255, 255, 0.045); cursor: pointer; transition: 0.15s; }
.pick:hover { border-color: rgba(0, 224, 198, 0.35); background: rgba(0, 224, 198, 0.04); }
.pleft { text-align: center; }
.pring { width: 72px; height: 72px; border-radius: 50%; margin: 0 auto; display: flex; align-items: center; justify-content: center; position: relative; }
.pring::before { content: ""; position: absolute; inset: 8px; border-radius: 50%; background: #0c1019; }
.pnum { position: relative; font-size: 24px; font-weight: 800; }
.pscore-lab { font-size: 11px; color: #8a93a8; margin-top: 7px; }
.pmid { min-width: 0; }
.pnm { font-size: 17px; font-weight: 700; display: flex; align-items: center; flex-wrap: wrap; gap: 8px; }
.pnm small { color: #5c6378; font-weight: 400; font-size: 12px; }
.weight { font-size: 11px; font-weight: 700; color: #00e0c6; background: rgba(0, 224, 198, 0.12); padding: 2px 10px; border-radius: 980px; }
.preason { font-size: 12.5px; color: #8a93a8; margin: 5px 0 10px; }
.radar { display: grid; grid-template-columns: 1fr 1fr; gap: 4px 18px; max-width: 460px; }
.rbar { display: flex; align-items: center; gap: 8px; font-size: 11px; }
.rk { width: 28px; color: #8a93a8; flex-shrink: 0; }
.rtrk { flex: 1; height: 5px; border-radius: 980px; background: rgba(255, 255, 255, 0.07); overflow: hidden; }
.rtrk i { display: block; height: 100%; border-radius: 980px; }
.rv { width: 22px; text-align: right; font-family: "SF Mono", Consolas, monospace; color: #c7cedb; }
.pplan { border-left: 1px solid rgba(255, 255, 255, 0.09); padding-left: 18px; }
.prow { display: flex; justify-content: space-between; align-items: baseline; font-size: 13px; padding: 4px 0; }
.prow .pk { color: #8a93a8; font-size: 12px; }
.prow .pv { font-weight: 700; font-family: "SF Mono", Consolas, monospace; }
.prow .pv small { font-size: 11px; font-weight: 600; }
.up { color: #00e69a; }
.down { color: #ff5470; }
.hint { color: #6b7384; font-size: 12px; margin: 12px 0 0; }

.btwrap { border: 1px solid rgba(255, 255, 255, 0.09); border-radius: 18px; padding: 20px; background: rgba(255, 255, 255, 0.045); }
.chart { position: relative; }
.svg { width: 100%; height: 150px; display: block; }
.line { fill: none; stroke-width: 2; vector-effect: non-scaling-stroke; }
.line.strat { stroke: #00e0c6; filter: drop-shadow(0 0 4px rgba(0, 224, 198, 0.4)); }
.line.bench { stroke: #5c6378; stroke-dasharray: 4 4; }
.legend { display: flex; gap: 18px; flex-wrap: wrap; margin-top: 10px; font-size: 12px; color: #c7cedb; }
.lg { display: inline-flex; align-items: center; gap: 7px; }
.lg.dim { color: #5c6378; margin-left: auto; }
.ls { width: 14px; height: 3px; border-radius: 2px; }
.ls.strat { background: #00e0c6; }
.ls.bench { background: #5c6378; }
.metrics { display: grid; grid-template-columns: repeat(6, 1fr); gap: 12px; margin-top: 20px; padding-top: 18px; border-top: 1px solid rgba(255, 255, 255, 0.08); }
.m { text-align: center; }
.m .mv { font-size: 22px; font-weight: 800; font-family: "SF Mono", Consolas, monospace; }
.m .ml { font-size: 11px; color: #8a93a8; margin-top: 4px; }
.sens { margin-top: 20px; padding-top: 18px; border-top: 1px solid rgba(255, 255, 255, 0.08); }
.senshead { font-size: 12px; color: #8a93a8; margin-bottom: 12px; }
.sensgrid { display: grid; grid-template-columns: 54px repeat(3, 1fr); gap: 5px; max-width: 420px; }
.sg { display: flex; align-items: center; justify-content: center; font-size: 12px; border-radius: 7px; padding: 9px 4px; }
.sg.corner { background: transparent; }
.sg.colh, .sg.rowh { color: #8a93a8; font-size: 11px; }
.sg.cell { font-weight: 700; font-family: "SF Mono", Consolas, monospace; color: #d6f5ea; border: 1px solid rgba(255, 255, 255, 0.06); }
.caveat { font-size: 12px; color: #8a93a8; line-height: 1.7; margin: 14px 0 0; padding: 14px 16px; border-radius: 12px; background: rgba(255, 207, 107, 0.05); box-shadow: inset 3px 0 0 #ffcf6b; }
.caveat b { color: #ffcf6b; }

.ranked { border: 1px solid rgba(255, 255, 255, 0.09); border-radius: 14px; overflow: hidden; background: rgba(255, 255, 255, 0.03); }
.rhead, .rrow { display: grid; grid-template-columns: 36px 1fr 90px 90px 60px 56px; align-items: center; padding: 10px 16px; font-size: 13px; }
.rhead { color: #8a93a8; font-size: 11px; border-bottom: 1px solid rgba(255, 255, 255, 0.09); }
.rrow { border-bottom: 1px solid rgba(255, 255, 255, 0.05); cursor: pointer; }
.rrow:last-child { border-bottom: none; }
.rrow:hover { background: rgba(255, 255, 255, 0.04); }
.ri { color: #5c6378; font-family: "SF Mono", Consolas, monospace; }
.rn { font-weight: 600; }
.rn small { color: #5c6378; font-weight: 400; margin-left: 7px; font-size: 11px; }
.rs { font-weight: 800; font-family: "SF Mono", Consolas, monospace; }

.foot { color: #5c6378; font-size: 12px; margin-top: 26px; line-height: 1.7; }

@media (max-width: 880px) {
  .topgrid { grid-template-columns: 1fr; }
  .pick { grid-template-columns: 72px 1fr; }
  .pplan { grid-column: 1 / -1; border-left: none; border-top: 1px solid rgba(255, 255, 255, 0.09); padding-left: 0; padding-top: 12px; }
  .metrics { grid-template-columns: repeat(3, 1fr); }
  .modes { grid-template-columns: 1fr; }
  .agrid { grid-template-columns: repeat(3, 1fr); }
}
</style>
