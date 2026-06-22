<script setup lang="ts">
import { ref, onMounted, computed, onUnmounted } from "vue";
import {
  loadFib, loadAiVeto, loadMonitor,
  type FibStrategy, type FibCandidate, type AiVeto, type AiVetoResult, type MonitorStatus,
} from "./useSentio";
import { useFibCheck } from "./useFibCheck";
import { useProvidersStore } from "../../stores/providers";

const emit = defineEmits<{ (e: "open-report", code: string): void }>();

// 左下角「供应商坞」当前选中的 API：AI 深研开启时，排雷层就走它。
const providers = useProvidersStore();
const apiName = computed(() => providers.current?.name || "当前 API");
// AI 深度排雷开关（默认关，省 token/时延）；开启则用当前 API 对候选做新闻研判。
const aiDeep = ref(false);

const fib = ref<FibStrategy | null>(null);
const aiVeto = ref<AiVeto | null>(null);
const monitor = ref<MonitorStatus | null>(null);
const loading = ref(true);
const showMatrix = ref(false);

const check = useFibCheck();
let offDone: (() => void) | null = null;

async function refresh() {
  loading.value = true;
  const [f, v, m] = await Promise.all([loadFib(), loadAiVeto(), loadMonitor()]);
  fib.value = f;
  aiVeto.value = v;
  monitor.value = m;
  loading.value = false;
}

// AI 排雷查表（code → 结果）+ 市场态势 + 样本外
const vetoMap = computed(() => {
  const m: Record<string, AiVetoResult> = {};
  for (const r of aiVeto.value?.results ?? []) m[r.code] = r;
  return m;
});
const regime = computed(() => fib.value?.regime ?? null);
const oos = computed(() => fib.value?.validation?.walkforward ?? null);
const sevColor: Record<string, string> = { ok: "#00e69a", warn: "#ffcf6b", err: "#ff5470" };
async function runNow() {
  await check.start(undefined, aiDeep.value);
}
onMounted(() => {
  refresh();
  providers.refresh();
  offDone = check.onDone((d) => {
    if (d.ok) refresh();
  });
});
onUnmounted(() => offDone?.());

const val = computed(() => fib.value?.validation ?? null);
const pooled = computed(() => val.value?.pooled ?? null);
const pf = computed(() => val.value?.portfolio ?? null);
const verdict = computed(() => val.value?.verdict ?? null);
const updated = computed(() =>
  fib.value?.updated_at ? fib.value.updated_at.replace("T", " ").slice(0, 16) : ""
);

const fresh = computed(() => (fib.value?.candidates ?? []).filter((c) => c.state === "fresh_entry"));
const holding = computed(() => (fib.value?.candidates ?? []).filter((c) => c.state === "holding"));
const watch = computed(() => (fib.value?.candidates ?? []).filter((c) => c.state === "watch"));

const stateMeta: Record<string, { label: string; color: string; tip: string }> = {
  fresh_entry: { label: "今日新进场", color: "#00e69a", tip: "金叉确认+站上趋势均线，可建仓" },
  holding: { label: "趋势持有", color: "#33e0ff", tip: "已在趋势中，站上均线继续持有/回踩可加" },
  watch: { label: "金叉在即", color: "#ffcf6b", tip: "快线逼近慢线，盯盘待进" },
};

// 权益曲线 → SVG
const W = 680;
const H = 150;
const PAD = 6;
function curvePath(key: "strat" | "bench"): string {
  const c = pf.value?.curve ?? [];
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

// 参数矩阵 heatmap
const matKs = computed(() => [...new Set((val.value?.param_matrix ?? []).map((r) => r.k))]);
const matMs = computed(() => [...new Set((val.value?.param_matrix ?? []).map((r) => r.m))].sort((a, b) => a - b));
function matCell(k: number, m: number) {
  return (val.value?.param_matrix ?? []).find((r) => r.k === k && r.m === m) ?? null;
}
function matColor(er: number | null): string {
  if (er == null) return "rgba(255,255,255,0.03)";
  const t = Math.max(0, Math.min(1, er / 2.5)); // 0→灰 2.5R→绿
  return `rgba(0, 230, 154, ${(0.06 + t * 0.34).toFixed(2)})`;
}

function payoffWidth(c: FibCandidate): string {
  const er = c.hist?.expectancy_r ?? 0;
  return Math.max(4, Math.min(100, (er / 5) * 100)) + "%";
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
          <div class="eyebrow">智投顾 · 斐波那契趋势机</div>
          <h1>斐波选股</h1>
          <div class="lead">金叉进场 · 斐波那契止损 · 站上均线一路持有 · 截断亏损让利润奔跑</div>
        </div>
        <div class="head-actions">
          <label
            class="aitoggle"
            :class="{ on: aiDeep }"
            :title="`开启后，AI 新闻排雷用左下角当前 API（${apiName}）做深度研判；关闭则只用离线关键词扫描`"
          >
            <input type="checkbox" v-model="aiDeep" :disabled="check.running.value" />
            <span class="sw"><span class="knob" /></span>
            <span class="aitxt">AI 深研 · <b>{{ apiName }}</b></span>
          </label>
          <button class="check" :disabled="check.running.value" @click="runNow">
            <span class="dot" :class="{ spin: check.running.value }"></span>
            {{ check.running.value ? "回测中…" : "斐波检查" }}
          </button>
        </div>
      </header>

      <!-- 系统健康 + 市场态势 状态条 -->
      <div v-if="monitor || regime" class="statusbar">
        <div v-if="monitor" class="sbitem" :title="Object.values(monitor.checks).map(c=>c.msg).join(' · ')">
          <span class="sdot" :style="{ background: sevColor[monitor.overall_sev] }"></span>
          系统：<b :style="{ color: sevColor[monitor.overall_sev] }">{{ monitor.overall }}</b>
          <small>数据/策略/账户/风控</small>
        </div>
        <div v-if="regime" class="sbitem" :title="regime.advice">
          市场态势：<b>{{ regime.label }}</b>
          <small>{{ regime.symbol }} 建议敞口 {{ (regime.exposure * 100).toFixed(0) }}%</small>
        </div>
        <div v-if="aiVeto" class="sbitem">
          AI 排雷：<b>{{ aiVeto.assessed }}</b> 只
          <small v-if="aiVeto.veto_count">否决 {{ aiVeto.veto_count }}</small>
          <small v-else>无硬红旗</small>
        </div>
      </div>

      <div v-if="check.running.value || check.ok.value === false" class="progress">
        <div class="ptop">
          <span class="plabel">{{ check.running.value ? "取价 → 事件回测 → 参数寻优 → 今日选股" : "检查未完成" }}</span>
          <span class="ppct">{{ check.pct.value }}%</span>
        </div>
        <div class="ptrack"><i :style="{ width: check.pct.value + '%' }"></i></div>
        <div class="plog">{{ check.lines.value[check.lines.value.length - 1] || check.lastMsg.value }}</div>
      </div>

      <div v-if="loading" class="empty">载入斐波那契策略…</div>
      <div v-else-if="!fib" class="empty">
        暂无数据。点右上「斐波检查」运行，或先跑
        <code>python data-pipeline/run_fib.py</code>
      </div>

      <template v-else>
        <!-- 有效性结论 -->
        <div v-if="verdict" class="verdict" :class="{ ok: verdict.effective }">
          <div class="vbadge">{{ verdict.effective ? "✅ 策略有效" : "⚠ 谨慎" }}</div>
          <div class="vtext">{{ verdict.headline }}</div>
        </div>

        <!-- 今日候选 -->
        <div class="sechead">⭐ 今日信号 · 新进场 {{ fresh.length }} · 持有 {{ holding.length }} · 待进 {{ watch.length }}</div>
        <div v-if="fib.candidates.length === 0" class="empty sm">今日无符合趋势条件的标的（震荡市常见，空仓也是一种纪律）。</div>
        <div class="cands">
          <div
            v-for="c in fib.candidates"
            :key="c.code"
            class="cand"
            :class="c.state"
            @click="openReport(c.code)"
          >
            <div class="cl">
              <div class="ctags">
                <span class="cstate" :style="{ color: stateMeta[c.state].color, borderColor: stateMeta[c.state].color }">
                  {{ stateMeta[c.state].label }}
                </span>
                <span
                  v-if="vetoMap[c.code]"
                  class="aibadge"
                  :class="vetoMap[c.code].veto ? 'veto' : (vetoMap[c.code].red_flags.length ? 'warn' : 'pass')"
                  :title="vetoMap[c.code].reason + (vetoMap[c.code].source==='llm' ? '（AI深研）' : '')"
                >
                  {{ vetoMap[c.code].veto ? "🔴 AI否决" : (vetoMap[c.code].red_flags.length ? "🟡 " + vetoMap[c.code].red_flags.slice(0,2).join("/") : "🟢 AI通过") }}
                </span>
              </div>
              <div class="cnm">{{ c.name }}<small>{{ c.code }} · {{ c.sector }}</small></div>
              <div class="creason">{{ c.reason }}</div>
            </div>
            <div class="cplan">
              <div class="prow"><span class="pk">参考买入</span><span class="pv">¥{{ c.entry }}</span></div>
              <div class="prow"><span class="pk">斐波止损</span><span class="pv down">¥{{ c.fib_stop }} <small>{{ c.fib_stop_pct }}%</small></span></div>
              <div class="prow"><span class="pk">{{ c.trail_ma_label }} 移动止损</span><span class="pv">¥{{ c.trail_ma }} <small>距{{ c.dist_to_ma_pct }}%</small></span></div>
              <div class="prow"><span class="pk">建议仓位</span><span class="pv gold">{{ c.suggest_pos_pct }}%</span></div>
            </div>
            <div class="chist">
              <div class="chk">该股历史信号战绩</div>
              <template v-if="c.hist">
                <div class="chrow"><b>{{ c.hist.trades }}</b><small>笔</small></div>
                <div class="chrow"><b>{{ c.hist.win_rate }}%</b><small>胜率</small></div>
                <div class="chrow"><b :class="c.hist.expectancy_r >= 0 ? 'up' : 'down'">{{ c.hist.expectancy_r >= 0 ? "+" : "" }}{{ c.hist.expectancy_r }}R</b><small>期望</small></div>
                <div class="chbar"><i :style="{ width: payoffWidth(c), background: c.hist.expectancy_r >= 0 ? '#00e69a' : '#ff5470' }"></i></div>
              </template>
              <div v-else class="chnone">无历史样本</div>
            </div>
          </div>
        </div>
        <p class="hint">
          规则：{{ fib.rules.entry }}。止损={{ fib.rules.stop }}；出场={{ fib.rules.exit }}。仓位 {{ fib.rules.size }}。
          ⚠ 个股历史样本少时（&lt;5 笔）期望R 参考意义有限。点卡片看个股报告。
        </p>

        <!-- 非对称收益结构 -->
        <template v-if="pooled">
          <div class="sechead">🎯 非对称收益结构验证 · {{ pooled.trades }} 笔全样本</div>
          <div class="asym">
            <div class="asymbars">
              <div class="ab">
                <div class="abtop"><span>平均盈利（让利润奔跑）</span><b class="up">+{{ pooled.avg_win_pct }}%</b></div>
                <div class="abtrk"><i class="up" :style="{ width: '100%' }"></i></div>
              </div>
              <div class="ab">
                <div class="abtop"><span>平均亏损（截断亏损）</span><b class="down">{{ pooled.avg_loss_pct }}%</b></div>
                <div class="abtrk"><i class="down" :style="{ width: Math.min(100, Math.abs(pooled.avg_loss_pct) / pooled.avg_win_pct * 100) + '%' }"></i></div>
              </div>
            </div>
            <div class="asymstats">
              <div class="as"><div class="asv">{{ pooled.win_rate }}%</div><div class="asl">胜率</div></div>
              <div class="as"><div class="asv gold">{{ pooled.payoff_ratio }}×</div><div class="asl">盈亏比</div></div>
              <div class="as"><div class="asv up">+{{ pooled.expectancy_r }}R</div><div class="asl">每笔期望</div></div>
              <div class="as"><div class="asv">{{ pooled.profit_factor }}</div><div class="asl">盈利因子</div></div>
              <div class="as"><div class="asv">{{ pooled.avg_bars }}</div><div class="asl">平均持仓(日)</div></div>
              <div class="as"><div class="asv up">+{{ pooled.max_win_pct }}%</div><div class="asl">最大盈利</div></div>
            </div>
          </div>
          <p class="hint">
            低胜率（{{ pooled.win_rate }}%）+ 高盈亏比（{{ pooled.payoff_ratio }}×）= 每笔期望 <b class="up">+{{ pooled.expectancy_r }}R</b>。
            出场构成：斐波止损 {{ pooled.exit_reasons.fib_stop || 0 }} 次（小亏） / 跌破均线 {{ pooled.exit_reasons.ma_break || 0 }} 次。
            这正是「胜率不重要、靠少数大趋势取胜」的赌徒赚赔率内核。
          </p>
        </template>

        <!-- 组合回测 vs 买入持有 -->
        <template v-if="pf">
          <div class="sechead">📈 组合回测 · 对标等权买入持有（{{ pf.years }} 年 · 最多 {{ pf.max_concurrent }} 并发 · 净于成本）</div>
          <div class="btwrap">
            <div class="chart">
              <svg :viewBox="`0 0 ${W} ${H}`" preserveAspectRatio="none" class="svg">
                <path :d="benchPath" class="line bench" />
                <path :d="stratPath" class="line strat" />
              </svg>
              <div class="legend">
                <span class="lg"><i class="ls strat"></i>斐波策略 +{{ pf.total_return }}%</span>
                <span class="lg"><i class="ls bench"></i>等权买入持有 +{{ pf.bench_total }}%</span>
                <span class="lg dim">{{ pf.start }} → {{ pf.end }}</span>
              </div>
            </div>
            <div class="metrics">
              <div class="m"><div class="mv" :style="{ color: pf.excess >= 0 ? '#00e69a' : '#ff5470' }">{{ pf.excess >= 0 ? "+" : "" }}{{ pf.excess }}%</div><div class="ml">超额基准</div></div>
              <div class="m"><div class="mv">{{ pf.cagr }}%</div><div class="ml">年化(CAGR)</div></div>
              <div class="m"><div class="mv down">{{ pf.max_drawdown }}%</div><div class="ml">最大回撤</div></div>
              <div class="m"><div class="mv">{{ pf.sharpe }}</div><div class="ml">夏普</div></div>
              <div class="m"><div class="mv">{{ pf.vol_ann }}%</div><div class="ml">年化波动</div></div>
              <div class="m"><div class="mv dim">{{ pf.bench_mdd }}%</div><div class="ml">基准回撤</div></div>
            </div>
          </div>
        </template>

        <!-- 样本外(OOS)诚实对照 -->
        <template v-if="oos && oos.oos_pooled && oos.is_pooled">
          <div class="sechead">🔬 样本外验证 · 防过拟合的诚实成绩（滚动选参：训练 {{ oos.window.train_months }} 月 → 检验 {{ oos.window.test_months }} 月）</div>
          <div class="oos">
            <div class="oosgrid">
              <div class="ooscol is">
                <div class="oostag">样本内（乐观上界·会高估）</div>
                <div class="oosrow"><span>每笔期望</span><b>+{{ oos.is_pooled.expectancy_r }}R</b></div>
                <div class="oosrow"><span>盈利因子</span><b>{{ oos.is_pooled.profit_factor }}</b></div>
                <div class="oosrow"><span>胜率</span><b>{{ oos.is_pooled.win_rate }}%</b></div>
              </div>
              <div class="oosarrow">→</div>
              <div class="ooscol oo">
                <div class="oostag hl">样本外（诚实·可信预期）</div>
                <div class="oosrow"><span>每笔期望</span><b class="up">+{{ oos.oos_pooled.expectancy_r }}R</b></div>
                <div class="oosrow"><span>盈利因子</span><b class="up">{{ oos.oos_pooled.profit_factor }}</b></div>
                <div class="oosrow"><span>胜率</span><b>{{ oos.oos_pooled.win_rate }}%</b></div>
                <div class="oosrow" v-if="oos.oos_portfolio"><span>组合年化</span><b>{{ oos.oos_portfolio.cagr }}%</b></div>
                <div class="oosrow" v-if="oos.oos_portfolio"><span>最大回撤</span><b class="down">{{ oos.oos_portfolio.max_drawdown }}%</b></div>
                <div class="oosrow" v-if="oos.oos_portfolio"><span>夏普</span><b>{{ oos.oos_portfolio.sharpe }}</b></div>
              </div>
            </div>
            <p class="oosnote" v-if="oos.verdict">
              <b :class="oos.verdict.effective ? 'up' : 'down'">{{ oos.verdict.effective ? "✅ edge 样本外稳健" : "⚠ edge 样本外偏弱" }}</b>
              ·保留样本内 <b>{{ oos.verdict.retention_pct }}%</b> 期望R。<b class="gold">对外汇报、上实盘一律以「样本外」为准</b>——样本内数字是技术上限，不是真实预期。
            </p>
          </div>
        </template>

        <!-- 参数稳健性 -->
        <div v-if="val && val.param_matrix.length" class="sechead clickable" @click="showMatrix = !showMatrix">
          {{ showMatrix ? "▾" : "▸" }} 参数稳健性 · 期望R 随「斐波系数 × 趋势均线」变化（普遍为正=非过拟合）
        </div>
        <div v-if="showMatrix && val" class="matrix">
          <div class="mgrid" :style="{ gridTemplateColumns: `64px repeat(${matMs.length}, 1fr)` }">
            <div class="mg corner">k＼m</div>
            <div v-for="m in matMs" :key="'h' + m" class="mg colh">EMA{{ m }}</div>
            <template v-for="k in matKs" :key="'r' + k">
              <div class="mg rowh">{{ k }}×ATR</div>
              <div
                v-for="m in matMs"
                :key="k + '-' + m"
                class="mg cell"
                :style="{ background: matColor(matCell(k, m)?.expectancy_r ?? null) }"
                :title="matCell(k, m) ? `${matCell(k,m)!.trades}笔 胜率${matCell(k,m)!.win_rate}% PF${matCell(k,m)!.profit_factor}` : ''"
              >
                {{ matCell(k, m) ? "+" + matCell(k, m)!.expectancy_r + "R" : "—" }}
              </div>
            </template>
          </div>
          <div v-if="val.slope_compare.length" class="slope">
            <div class="slopehead">趋势闸价值（只在真趋势进场 vs 不过滤）</div>
            <div class="sloperow" v-for="s in val.slope_compare" :key="String(s.require_slope)">
              <span class="sl" :class="{ on: s.require_slope }">{{ s.require_slope ? "趋势闸 ON" : "趋势闸 OFF" }}</span>
              <span>交易 <b>{{ s.trades }}</b></span>
              <span>胜率 <b>{{ s.win_rate }}%</b></span>
              <span>盈利因子 <b>{{ s.profit_factor }}</b></span>
              <span>期望 <b class="up">+{{ s.expectancy_r }}R</b></span>
            </div>
          </div>
          <div class="cfgline">运行配置：<b>{{ fib.config.label }}</b> · 凯利折扣 {{ (fib.config.kelly_fraction * 100).toFixed(0) }}% · 单笔风险 {{ (fib.config.risk_per_trade * 100).toFixed(0) }}% · 往返成本 {{ (fib.config.cost_roundtrip * 100).toFixed(1) }}%</div>
        </div>

        <p class="caveat">
          ⚠ 诚实提示：回测宇宙为<b>当下龙头精选</b>，存在「事后选择偏差」，绝对收益会被高估；趋势策略在
          <b>震荡市必然连续小亏</b>，靠少数大趋势的非对称盈利覆盖。更应看<b>相对基准超额</b>与<b>回撤/夏普</b>。回测有效≠未来有效。
        </p>
        <p class="foot">{{ fib.disclaimer }}<span v-if="updated"> · 更新于 {{ updated }}</span></p>
      </template>
    </div>
  </div>
</template>

<style scoped>
.sentio-view {
  flex: 1; height: 100vh; overflow-y: auto; background: #070a12;
  background-image: radial-gradient(circle at 15% 5%, rgba(0, 224, 198, 0.12), transparent 40%),
    radial-gradient(circle at 85% 12%, rgba(91, 140, 255, 0.1), transparent 42%);
  color: #f0f3fa; font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Microsoft YaHei", sans-serif;
}
.inner { max-width: 1000px; margin: 0 auto; padding: 34px 32px 80px; }
.head { display: flex; align-items: flex-start; gap: 16px; margin-bottom: 6px; }
.eyebrow { font-size: 12px; font-weight: 600; letter-spacing: 0.06em; background: linear-gradient(120deg, #00e0c6, #5b8cff); -webkit-background-clip: text; background-clip: text; color: transparent; }
h1 { font-size: 32px; font-weight: 800; letter-spacing: -0.02em; margin: 6px 0 4px; }
.lead { color: #8a93a8; font-size: 14px; }

.head-actions { margin-left: auto; display: flex; align-items: center; gap: 12px; flex-shrink: 0; }
.aitoggle { display: inline-flex; align-items: center; gap: 7px; cursor: pointer; user-select: none; font-size: 12px; color: #8a93a8; white-space: nowrap; }
.aitoggle input { display: none; }
.aitoggle .sw { width: 30px; height: 17px; border-radius: 9px; background: rgba(255,255,255,0.12); position: relative; transition: background 0.16s; flex-shrink: 0; }
.aitoggle.on .sw { background: linear-gradient(120deg, #00e0c6, #5b8cff); }
.aitoggle .knob { position: absolute; top: 2px; left: 2px; width: 13px; height: 13px; border-radius: 50%; background: #fff; transition: transform 0.16s; }
.aitoggle.on .knob { transform: translateX(13px); }
.aitoggle .aitxt b { color: #c5cde0; font-weight: 700; }
.aitoggle.on .aitxt { color: #c5cde0; }
.check { display: inline-flex; align-items: center; gap: 8px; font-size: 13px; font-weight: 700; color: #05121f;
  background: linear-gradient(120deg, #00e0c6, #5b8cff); border: none; border-radius: 980px; padding: 9px 20px; cursor: pointer; white-space: nowrap;
  box-shadow: 0 6px 20px rgba(0, 224, 198, 0.28); transition: 0.15s; }
.check:hover { filter: brightness(1.06); transform: translateY(-1px); }
.check:disabled { opacity: 0.7; cursor: default; transform: none; }
.check .dot { width: 8px; height: 8px; border-radius: 50%; background: #05121f; }
.check .dot.spin { border: 2px solid rgba(5, 18, 31, 0.35); border-top-color: #05121f; background: transparent; animation: spin 0.7s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }

.progress { border: 1px solid rgba(0, 224, 198, 0.25); border-radius: 14px; padding: 14px 18px; background: rgba(0, 224, 198, 0.05); margin: 18px 0 6px; }
.ptop { display: flex; justify-content: space-between; font-size: 12px; color: #8a93a8; margin-bottom: 8px; }
.ptop .ppct { color: #00e0c6; font-weight: 700; font-family: "SF Mono", Consolas, monospace; }
.ptrack { height: 6px; border-radius: 980px; background: rgba(255, 255, 255, 0.08); overflow: hidden; }
.ptrack i { display: block; height: 100%; border-radius: 980px; background: linear-gradient(90deg, #00e0c6, #5b8cff); transition: width 0.4s ease; }
.plog { margin-top: 9px; font-size: 11.5px; color: #6b7384; font-family: "SF Mono", Consolas, monospace; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

.empty { color: #8a93a8; padding: 50px 0; text-align: center; font-size: 14px; }
.empty.sm { padding: 22px 0; }
.empty code { background: rgba(255, 255, 255, 0.08); padding: 2px 8px; border-radius: 6px; color: #a9d8ff; }

.verdict { display: flex; align-items: center; gap: 16px; margin: 22px 0 4px; padding: 16px 20px; border-radius: 16px;
  border: 1px solid rgba(255, 207, 107, 0.3); background: rgba(255, 207, 107, 0.05); }
.verdict.ok { border-color: rgba(0, 230, 154, 0.35); background: linear-gradient(120deg, rgba(0, 230, 154, 0.08), transparent 75%); }
.vbadge { flex-shrink: 0; font-size: 15px; font-weight: 800; }
.vtext { font-size: 13.5px; color: #d6dceb; line-height: 1.7; }

.sechead { font-size: 13px; font-weight: 700; letter-spacing: 0.04em; color: #8a93a8; margin: 34px 0 14px; }
.sechead.clickable { cursor: pointer; user-select: none; }
.sechead.clickable:hover { color: #c7cedb; }

.cands { display: grid; gap: 12px; }
.cand { display: grid; grid-template-columns: 1fr 210px 168px; gap: 18px; align-items: stretch;
  border: 1px solid rgba(255, 255, 255, 0.09); border-radius: 18px; padding: 16px 20px; background: rgba(255, 255, 255, 0.045); cursor: pointer; transition: 0.15s; }
.cand:hover { border-color: rgba(0, 224, 198, 0.35); background: rgba(0, 224, 198, 0.04); }
.cand.fresh_entry { box-shadow: inset 3px 0 0 #00e69a; }
.cand.holding { box-shadow: inset 3px 0 0 #33e0ff; }
.cand.watch { box-shadow: inset 3px 0 0 #ffcf6b; }
.cstate { display: inline-block; font-size: 11px; font-weight: 700; padding: 2px 10px; border: 1px solid; border-radius: 980px; }
.cnm { font-size: 17px; font-weight: 700; margin: 8px 0 4px; }
.cnm small { color: #5c6378; font-weight: 400; font-size: 12px; margin-left: 8px; }
.creason { font-size: 12.5px; color: #8a93a8; line-height: 1.5; }
.cplan { border-left: 1px solid rgba(255, 255, 255, 0.09); padding-left: 18px; display: flex; flex-direction: column; justify-content: center; }
.prow { display: flex; justify-content: space-between; align-items: baseline; font-size: 12.5px; padding: 3px 0; }
.prow .pk { color: #8a93a8; }
.prow .pv { font-weight: 700; font-family: "SF Mono", Consolas, monospace; }
.prow .pv small { font-size: 10.5px; font-weight: 600; opacity: 0.8; }
.chist { border-left: 1px solid rgba(255, 255, 255, 0.09); padding-left: 18px; display: flex; flex-direction: column; justify-content: center; gap: 4px; }
.chk { font-size: 10.5px; color: #6b7384; margin-bottom: 2px; }
.chrow { display: flex; align-items: baseline; gap: 6px; font-size: 12px; }
.chrow b { font-family: "SF Mono", Consolas, monospace; font-size: 14px; }
.chrow small { color: #8a93a8; font-size: 10.5px; }
.chbar { height: 5px; border-radius: 980px; background: rgba(255, 255, 255, 0.07); overflow: hidden; margin-top: 4px; }
.chbar i { display: block; height: 100%; border-radius: 980px; }
.chnone { font-size: 11px; color: #5c6378; }
.up { color: #00e69a; } .down { color: #ff5470; } .gold { color: #ffcf6b; }
.hint { color: #6b7384; font-size: 12px; margin: 12px 0 0; line-height: 1.7; }

/* 系统健康 + 态势 状态条 */
.statusbar { display: flex; flex-wrap: wrap; gap: 10px; margin: 16px 0 4px; }
.sbitem { display: inline-flex; align-items: center; gap: 7px; font-size: 12.5px; color: #c7cedb;
  border: 1px solid rgba(255, 255, 255, 0.09); border-radius: 980px; padding: 7px 15px; background: rgba(255, 255, 255, 0.04); }
.sbitem b { font-weight: 700; }
.sbitem small { color: #6b7384; font-size: 11px; }
.sdot { width: 8px; height: 8px; border-radius: 50%; box-shadow: 0 0 8px currentColor; }

/* AI 排雷徽章 */
.ctags { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
.aibadge { font-size: 10.5px; font-weight: 700; padding: 2px 9px; border-radius: 980px; border: 1px solid; }
.aibadge.pass { color: #00e69a; border-color: rgba(0, 230, 154, 0.4); background: rgba(0, 230, 154, 0.08); }
.aibadge.warn { color: #ffcf6b; border-color: rgba(255, 207, 107, 0.4); background: rgba(255, 207, 107, 0.08); }
.aibadge.veto { color: #ff5470; border-color: rgba(255, 84, 112, 0.5); background: rgba(255, 84, 112, 0.1); }

/* 样本外面板 */
.oos { border: 1px solid rgba(255, 255, 255, 0.09); border-radius: 18px; padding: 20px; background: rgba(255, 255, 255, 0.045); }
.oosgrid { display: flex; align-items: stretch; gap: 14px; }
.ooscol { flex: 1; border: 1px solid rgba(255, 255, 255, 0.08); border-radius: 14px; padding: 14px 16px; }
.ooscol.is { opacity: 0.72; }
.ooscol.oo { border-color: rgba(0, 230, 154, 0.3); background: rgba(0, 230, 154, 0.04); }
.oostag { font-size: 11.5px; color: #8a93a8; margin-bottom: 10px; font-weight: 600; }
.oostag.hl { color: #00e69a; }
.oosrow { display: flex; justify-content: space-between; align-items: baseline; font-size: 12.5px; padding: 4px 0; color: #8a93a8; }
.oosrow b { font-family: "SF Mono", Consolas, monospace; font-size: 14px; color: #d6dceb; }
.oosarrow { display: flex; align-items: center; color: #5c6378; font-size: 20px; }
.oosnote { font-size: 12px; color: #8a93a8; line-height: 1.7; margin: 14px 0 0; }
.oosnote b { font-weight: 700; }
@media (max-width: 880px) {
  .oosgrid { flex-direction: column; }
  .oosarrow { transform: rotate(90deg); justify-content: center; }
}
.hint b { color: #c7cedb; }

.asym { border: 1px solid rgba(255, 255, 255, 0.09); border-radius: 18px; padding: 20px; background: rgba(255, 255, 255, 0.045); }
.asymbars { display: flex; flex-direction: column; gap: 14px; }
.ab .abtop { display: flex; justify-content: space-between; font-size: 12.5px; color: #8a93a8; margin-bottom: 6px; }
.ab .abtop b { font-family: "SF Mono", Consolas, monospace; font-size: 14px; }
.abtrk { height: 10px; border-radius: 980px; background: rgba(255, 255, 255, 0.06); overflow: hidden; }
.abtrk i { display: block; height: 100%; border-radius: 980px; }
.abtrk i.up { background: linear-gradient(90deg, #00e69a, #33e0ff); }
.abtrk i.down { background: linear-gradient(90deg, #ff5470, #ff8a5c); }
.asymstats { display: grid; grid-template-columns: repeat(6, 1fr); gap: 12px; margin-top: 20px; padding-top: 18px; border-top: 1px solid rgba(255, 255, 255, 0.08); }
.as { text-align: center; }
.as .asv { font-size: 21px; font-weight: 800; font-family: "SF Mono", Consolas, monospace; }
.as .asv.up { color: #00e69a; } .as .asv.gold { color: #ffcf6b; }
.as .asl { font-size: 11px; color: #8a93a8; margin-top: 4px; }

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
.ls.strat { background: #00e0c6; } .ls.bench { background: #5c6378; }
.metrics { display: grid; grid-template-columns: repeat(6, 1fr); gap: 12px; margin-top: 20px; padding-top: 18px; border-top: 1px solid rgba(255, 255, 255, 0.08); }
.m { text-align: center; }
.m .mv { font-size: 22px; font-weight: 800; font-family: "SF Mono", Consolas, monospace; }
.m .mv.dim { color: #5c6378; }
.m .ml { font-size: 11px; color: #8a93a8; margin-top: 4px; }

.matrix { border: 1px solid rgba(255, 255, 255, 0.09); border-radius: 16px; padding: 18px; background: rgba(255, 255, 255, 0.03); }
.mgrid { display: grid; gap: 5px; max-width: 460px; }
.mg { display: flex; align-items: center; justify-content: center; font-size: 12px; border-radius: 7px; padding: 9px 4px; }
.mg.corner { color: #5c6378; font-size: 11px; }
.mg.colh, .mg.rowh { color: #8a93a8; font-size: 11px; }
.mg.cell { font-weight: 700; font-family: "SF Mono", Consolas, monospace; color: #d6f5ea; border: 1px solid rgba(255, 255, 255, 0.06); }
.slope { margin-top: 18px; padding-top: 16px; border-top: 1px solid rgba(255, 255, 255, 0.08); }
.slopehead { font-size: 12px; color: #8a93a8; margin-bottom: 10px; }
.sloperow { display: flex; align-items: center; gap: 18px; font-size: 12.5px; color: #8a93a8; padding: 5px 0; }
.sloperow b { color: #d6f5ea; font-family: "SF Mono", Consolas, monospace; }
.sl { font-size: 11px; font-weight: 700; padding: 2px 10px; border-radius: 980px; background: rgba(255, 255, 255, 0.06); color: #8a93a8; min-width: 92px; text-align: center; }
.sl.on { background: rgba(0, 230, 154, 0.14); color: #00e69a; }
.cfgline { margin-top: 16px; font-size: 11.5px; color: #6b7384; }
.cfgline b { color: #c7cedb; }

.caveat { font-size: 12px; color: #8a93a8; line-height: 1.7; margin: 24px 0 0; padding: 14px 16px; border-radius: 12px; background: rgba(255, 207, 107, 0.05); box-shadow: inset 3px 0 0 #ffcf6b; }
.caveat b { color: #ffcf6b; }
.foot { color: #5c6378; font-size: 12px; margin-top: 18px; line-height: 1.7; }

@media (max-width: 880px) {
  .cand { grid-template-columns: 1fr; }
  .cplan, .chist { border-left: none; border-top: 1px solid rgba(255, 255, 255, 0.09); padding-left: 0; padding-top: 12px; }
  .asymstats, .metrics { grid-template-columns: repeat(3, 1fr); }
}
</style>
