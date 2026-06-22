<script setup lang="ts">
// 账户管理：连券商(easytrader)看真实账户/持仓，结合诊断给操作；下单默认每单弹窗确认，
// 「自动交易」总开关默认关，点开才允许额度内自动；所有下单后端强制过风控三闸。
import { ref, onMounted, computed } from "vue";
import {
  loadAccount, brokerStatus, brokerSync, brokerOrder, brokerResetSim,
  loadBrokerConfig, saveBrokerConfig,
  type Account, type BrokerConfig, type OrderResult, type AcctPosition,
} from "./useSentio";

const acct = ref<Account | null>(null);
const cfg = ref<BrokerConfig | null>(null);
const loading = ref(true);
const busy = ref(false);
const msg = ref("");

// 下单工单
const oAction = ref<"BUY" | "SELL">("BUY");
const oCode = ref("");
const oShares = ref("");
const oPrice = ref("");
const pending = ref<null | { action: "BUY" | "SELL"; code: string; shares: number; price: number }>(null);
const lastResult = ref<OrderResult | null>(null);

async function refresh() {
  loading.value = true;
  const [a, c] = await Promise.all([loadAccount(), loadBrokerConfig()]);
  acct.value = a;
  cfg.value = c;
  loading.value = false;
}
onMounted(refresh);

function flash(m: string) {
  msg.value = m;
  setTimeout(() => (msg.value = ""), 2600);
}

async function doStatus() {
  busy.value = true;
  try {
    acct.value = await brokerStatus();
    flash("账户已刷新");
  } catch (e) {
    flash("刷新失败：" + e);
  } finally {
    busy.value = false;
  }
}
async function doSync() {
  busy.value = true;
  try {
    const r = await brokerSync();
    acct.value = r.account;
    flash(`已同步 ${r.synced} 只持仓 → 自选诊断将按真实成本算`);
  } catch (e) {
    flash("同步失败：" + e);
  } finally {
    busy.value = false;
  }
}
async function doResetSim() {
  if (!confirm("重置模拟盘？将清空模拟持仓与当日额度计数。")) return;
  busy.value = true;
  try {
    await brokerResetSim();
    await doStatus();
  } finally {
    busy.value = false;
  }
}

async function saveConfig() {
  if (!cfg.value) return;
  busy.value = true;
  try {
    await saveBrokerConfig(cfg.value);
    flash("券商配置已保存");
    await doStatus();
  } catch (e) {
    flash("保存失败：" + e);
  } finally {
    busy.value = false;
  }
}

// 打开/关闭自动交易总开关（高危，二次确认）
async function toggleAuto() {
  if (!cfg.value) return;
  if (!cfg.value.auto_trade) {
    if (!confirm("⚠️ 打开「自动交易」后，AI 将在你设定的额度内【自动买卖真实账户】，无需逐单确认。\n\n确定打开吗？（建议先用模拟盘验证策略稳定后再开）")) return;
  }
  cfg.value.auto_trade = !cfg.value.auto_trade;
  await saveConfig();
}

// 下单：先校验 → 弹确认框（默认路径，永远要确认）
function submitOrder() {
  const code = (oCode.value.match(/\d{6}/) ?? [])[0];
  const shares = parseInt(oShares.value, 10);
  if (!code) return flash("请输入 6 位股票代码");
  if (!shares || shares <= 0 || shares % 100 !== 0) return flash("股数须为 100 的整数倍");
  const price = parseFloat(oPrice.value) || 0; // 0 = 用最新价
  pending.value = { action: oAction.value, code, shares, price };
  lastResult.value = null;
}
async function confirmOrder() {
  if (!pending.value) return;
  busy.value = true;
  const p = pending.value;
  try {
    const r = await brokerOrder(p.action, p.code, p.shares, p.price || undefined);
    lastResult.value = r;
    pending.value = null;
    if (r.ok) {
      flash(`${p.action === "BUY" ? "买入" : "卖出"}已${acct.value?.adapter === "sim" ? "模拟成交" : "提交券商"}`);
      oShares.value = oPrice.value = "";
      await doStatus();
    } else {
      flash(r.blocked ? "被风控拦截：" + r.blocked : "下单失败：" + (r.msg ?? ""));
    }
  } catch (e) {
    flash("下单异常：" + e);
  } finally {
    busy.value = false;
  }
}
function cancelOrder() {
  pending.value = null;
}
function quickFill(p: AcctPosition, action: "BUY" | "SELL") {
  oAction.value = action;
  oCode.value = p.code;
  oShares.value = action === "SELL" ? String(p.shares) : "100";
  oPrice.value = "";
}

const positions = computed(() => acct.value?.positions ?? []);
const bal = computed(() => acct.value?.balance ?? null);
const connected = computed(() => acct.value?.connected ?? false);
const isSim = computed(() => (cfg.value?.adapter ?? "sim") === "sim");
const updated = computed(() =>
  acct.value?.updated_at ? acct.value.updated_at.replace("T", " ").slice(0, 16) : ""
);
function pnlColor(v: number) { return v > 0 ? "#ff5470" : v < 0 ? "#00e69a" : "#8a93a8"; }
const orderAmount = computed(() => {
  const sh = parseInt(oShares.value, 10) || 0;
  const pr = parseFloat(oPrice.value) || 0;
  return pr > 0 ? (sh * pr).toFixed(0) : "按最新价";
});
</script>

<template>
  <div class="sentio-view">
    <div class="inner">
      <header class="head">
        <div>
          <div class="eyebrow">智投顾 · 账户管理</div>
          <h1>账户</h1>
        </div>
        <div class="live" v-if="updated">更新 {{ updated }}</div>
      </header>
      <p class="sub">
        连接券商看真实账户/持仓，结合自选诊断决定操作。<b>下单默认每单弹窗确认</b>；
        「自动交易」总开关默认关，点开后才允许在你设定的额度内自动买卖。所有下单都强制过
        <b>风控三闸</b>（单笔/单日额度、单票仓位上限），任一不过即拦截，绝不静默成交。
      </p>

      <div v-if="msg" class="toast">{{ msg }}</div>

      <!-- 连接状态 -->
      <div class="row2">
        <div class="card">
          <div class="ctitle">连接</div>
          <div class="conn">
            <span class="dot" :class="{ on: connected }"></span>
            <b>{{ isSim ? "模拟盘" : "真实盘 · easytrader" }}</b>
            <span class="cstate">{{ connected ? "已连接" : "未连接" }}</span>
          </div>
          <div v-if="acct?.error" class="err">{{ acct.error }}</div>
          <div class="btns">
            <button class="btn ghost sm" :disabled="busy" @click="doStatus">刷新账户</button>
            <button class="btn ghost sm" :disabled="busy" @click="doSync">同步持仓→诊断</button>
            <button v-if="isSim" class="btn ghost sm" :disabled="busy" @click="doResetSim">重置模拟盘</button>
          </div>
        </div>

        <div class="card" v-if="bal">
          <div class="ctitle">资产</div>
          <div class="assets">
            <div class="acell"><span>总资产</span><b>{{ bal.total.toLocaleString() }}</b></div>
            <div class="acell"><span>可用现金</span><b>{{ bal.cash.toLocaleString() }}</b></div>
            <div class="acell"><span>持仓市值</span><b>{{ bal.market_value.toLocaleString() }}</b></div>
            <div class="acell"><span>今日已买</span><b>{{ (acct?.day_spent ?? 0).toLocaleString() }}</b></div>
          </div>
        </div>
      </div>

      <!-- 券商配置 -->
      <div class="card" v-if="cfg">
        <div class="ctitle">券商配置</div>
        <div class="cfgrow">
          <label>对接方式</label>
          <select v-model="cfg.adapter">
            <option value="sim">模拟盘（推荐先用）</option>
            <option value="universal_client">真实盘 · 同花顺通用客户端（华泰/银河/国君/海通等）</option>
            <option value="ths">真实盘 · 同花顺</option>
          </select>
        </div>
        <template v-if="!isSim">
          <div class="cfgrow">
            <label>客户端 exe 路径</label>
            <input v-model="cfg.easytrader.exe_path" placeholder="如 C:\\…\\xiadan.exe（同花顺通用版下单程序）" />
          </div>
          <div class="warn">
            真实盘需本机已装并登录对应券商 PC 客户端，且 <code>pip install easytrader</code>。
            首次请用模拟盘验证策略稳定后再切真实盘。
          </div>
        </template>
        <div class="cfgrow limits">
          <div><label>单笔额度(元)</label><input v-model.number="cfg.limits.per_order" type="number" /></div>
          <div><label>单日买入额度(元)</label><input v-model.number="cfg.limits.per_day" type="number" /></div>
          <div><label>单票仓位上限(%)</label><input v-model.number="cfg.limits.max_pos_pct" type="number" /></div>
        </div>
        <div class="autorow" :class="{ on: cfg.auto_trade }">
          <div>
            <div class="atitle">自动交易总开关
              <span class="abadge" :class="{ on: cfg.auto_trade }">{{ cfg.auto_trade ? "已开启" : "已关闭" }}</span>
            </div>
            <div class="adesc">关闭=每单需你弹窗确认（安全）；开启=AI 在上面额度内自动买卖真实账户（高风险）。</div>
          </div>
          <button class="switch" :class="{ on: cfg.auto_trade }" :disabled="busy" @click="toggleAuto">
            <span class="knob"></span>
          </button>
        </div>
        <div class="btns"><button class="btn primary sm" :disabled="busy" @click="saveConfig">保存配置</button></div>
      </div>

      <!-- 下单工单 -->
      <div class="card">
        <div class="ctitle">下单 <span class="hint-inline">（提交后会弹窗让你确认，确认才执行）</span></div>
        <div class="ticket">
          <div class="seg">
            <button :class="{ on: oAction === 'BUY' }" @click="oAction = 'BUY'">买入</button>
            <button :class="{ on: oAction === 'SELL', sell: true }" @click="oAction = 'SELL'">卖出</button>
          </div>
          <input v-model="oCode" placeholder="代码 6位" class="t-code" />
          <input v-model="oShares" placeholder="股数(100整数倍)" class="t-sh" />
          <input v-model="oPrice" placeholder="价格(留空=最新价)" class="t-pr" />
          <span class="amt">≈ {{ orderAmount }}</span>
          <button class="btn primary sm" :disabled="busy" @click="submitOrder">提交</button>
        </div>
        <div v-if="lastResult" class="oresult" :class="{ bad: !lastResult.ok }">
          <template v-if="lastResult.ok">
            ✓ {{ lastResult.action === 'BUY' ? '买入' : '卖出' }} {{ lastResult.name || lastResult.code }}
            {{ lastResult.shares }}股 @ {{ lastResult.price }}（{{ lastResult.amount }}元）{{ lastResult.msg }}
          </template>
          <template v-else>
            ✗ {{ lastResult.blocked ? '风控拦截：' + lastResult.blocked : (lastResult.msg || '下单失败') }}
          </template>
        </div>
      </div>

      <!-- 持仓 -->
      <div class="card">
        <div class="ctitle">持仓 <span class="hint-inline">{{ positions.length }} 只</span></div>
        <div v-if="!positions.length" class="empty">暂无持仓</div>
        <table v-else class="ptable">
          <thead>
            <tr><th>代码</th><th>名称</th><th>股数</th><th>成本</th><th>现价</th><th>盈亏</th><th>市值</th><th></th></tr>
          </thead>
          <tbody>
            <tr v-for="p in positions" :key="p.code">
              <td class="mono">{{ p.code }}</td>
              <td>{{ p.name }}</td>
              <td>{{ p.shares }}</td>
              <td class="mono">{{ p.cost }}</td>
              <td class="mono">{{ p.price }}</td>
              <td class="mono" :style="{ color: pnlColor(p.pnl) }">{{ p.pnl_pct }}%</td>
              <td class="mono">{{ p.market_value.toLocaleString() }}</td>
              <td class="qbtns">
                <button @click="quickFill(p, 'BUY')">加</button>
                <button class="sell" @click="quickFill(p, 'SELL')">减</button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <p class="foot">
        券商对接基于开源 easytrader 自动化你本机的券商客户端，账号密码不经过本应用、不上传任何服务器。
        AI 仅按规则给操作建议/下单，市场有风险，自动交易风险更高，盈亏自负。
      </p>
    </div>

    <!-- 下单确认弹窗（默认安全路径） -->
    <div v-if="pending" class="modal-mask" @click.self="cancelOrder">
      <div class="modal">
        <div class="mhead" :class="pending.action === 'BUY' ? 'buy' : 'sell'">
          确认{{ pending.action === 'BUY' ? '买入' : '卖出' }}
        </div>
        <div class="mbody">
          <div class="mrow"><span>方向</span><b>{{ pending.action === 'BUY' ? '买入' : '卖出' }}</b></div>
          <div class="mrow"><span>代码</span><b class="mono">{{ pending.code }}</b></div>
          <div class="mrow"><span>股数</span><b>{{ pending.shares }}</b></div>
          <div class="mrow"><span>价格</span><b>{{ pending.price > 0 ? pending.price : '最新价' }}</b></div>
          <div class="mrow"><span>预估金额</span><b>{{ pending.price > 0 ? (pending.shares * pending.price).toFixed(0) : '按最新价' }}</b></div>
          <div class="mnote">提交后将{{ isSim ? '在模拟盘成交' : '发送到真实券商客户端' }}，并先过风控三闸校验。</div>
        </div>
        <div class="mbtns">
          <button class="btn ghost" @click="cancelOrder">取消</button>
          <button class="btn primary" :disabled="busy" @click="confirmOrder">{{ busy ? '提交中…' : '确认下单' }}</button>
        </div>
      </div>
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
.head { display: flex; align-items: flex-end; gap: 16px; margin-bottom: 6px; }
.eyebrow {
  font-size: 12px; font-weight: 600; letter-spacing: 0.06em;
  background: linear-gradient(120deg, #5b8cff, #00e0c6); -webkit-background-clip: text; background-clip: text; color: transparent;
}
h1 { font-size: 32px; font-weight: 800; letter-spacing: -0.02em; margin: 6px 0 0; }
.live { margin-left: auto; font-size: 12px; color: #8a93a8; }
.sub { color: #8a93a8; font-size: 13px; margin: 0 0 16px; max-width: 760px; line-height: 1.7; }
.sub b { color: #c4cad6; }
.toast { background: rgba(0,230,154,0.12); color: #00e69a; font-size: 12.5px; padding: 8px 14px; border-radius: 10px; margin-bottom: 12px; }

.row2 { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
@media (max-width: 720px) { .row2 { grid-template-columns: 1fr; } }
.card { border: 1px solid rgba(255,255,255,0.09); border-radius: 16px; padding: 16px 18px; background: rgba(255,255,255,0.045); margin-bottom: 14px; }
.ctitle { font-size: 13px; font-weight: 700; margin-bottom: 12px; }
.hint-inline { color: #6b7384; font-weight: 400; font-size: 11.5px; margin-left: 6px; }

.conn { display: flex; align-items: center; gap: 9px; font-size: 15px; }
.dot { width: 9px; height: 9px; border-radius: 50%; background: #6b7384; }
.dot.on { background: #00e69a; box-shadow: 0 0 8px #00e69a; }
.cstate { font-size: 12px; color: #8a93a8; }
.err { color: #ff5470; font-size: 12px; margin-top: 8px; line-height: 1.5; }
.btns { display: flex; gap: 8px; margin-top: 12px; flex-wrap: wrap; }
.btn { border: none; border-radius: 9px; font-size: 13px; padding: 8px 16px; cursor: pointer; }
.btn.sm { padding: 6px 13px; font-size: 12px; }
.btn.primary { background: linear-gradient(120deg, #5b8cff, #00e0c6); color: #04121a; font-weight: 700; }
.btn.ghost { background: rgba(255,255,255,0.07); color: #c4cad6; }
.btn.ghost:hover { background: rgba(255,255,255,0.12); }
.btn:disabled { opacity: 0.5; cursor: default; }

.assets { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.acell span { font-size: 11px; color: #6b7384; display: block; }
.acell b { font-size: 19px; font-family: "SF Mono", Consolas, monospace; }

.cfgrow { display: flex; align-items: center; gap: 12px; margin-bottom: 10px; }
.cfgrow label { font-size: 12px; color: #8a93a8; min-width: 110px; }
.cfgrow select, .cfgrow input {
  flex: 1; background: rgba(0,0,0,0.25); border: 1px solid rgba(255,255,255,0.1);
  border-radius: 8px; color: #f0f3fa; font-size: 12.5px; padding: 7px 10px;
}
.cfgrow.limits { gap: 14px; }
.cfgrow.limits > div { flex: 1; }
.cfgrow.limits label { display: block; min-width: 0; margin-bottom: 4px; }
.cfgrow.limits input { width: 100%; box-sizing: border-box; }
.warn { font-size: 11.5px; color: #ffcf6b; background: rgba(255,207,107,0.08); border-radius: 9px; padding: 9px 12px; margin-bottom: 10px; line-height: 1.6; }
.warn code, code { font-family: "SF Mono", Consolas, monospace; background: rgba(255,255,255,0.08); padding: 1px 6px; border-radius: 5px; }

.autorow { display: flex; align-items: center; gap: 14px; border: 1px solid rgba(255,255,255,0.1); border-radius: 12px; padding: 12px 14px; margin: 12px 0; }
.autorow.on { border-color: rgba(255,84,112,0.4); background: rgba(255,84,112,0.06); }
.atitle { font-size: 13.5px; font-weight: 700; }
.abadge { font-size: 10.5px; padding: 2px 8px; border-radius: 980px; margin-left: 8px; background: rgba(138,147,168,0.2); color: #8a93a8; }
.abadge.on { background: rgba(255,84,112,0.18); color: #ff5470; }
.adesc { font-size: 11.5px; color: #8a93a8; margin-top: 4px; line-height: 1.5; }
.switch { margin-left: auto; width: 46px; height: 26px; border-radius: 980px; border: none; background: rgba(255,255,255,0.14); position: relative; cursor: pointer; flex-shrink: 0; transition: 0.2s; }
.switch.on { background: #ff5470; }
.knob { position: absolute; top: 3px; left: 3px; width: 20px; height: 20px; border-radius: 50%; background: #fff; transition: 0.2s; }
.switch.on .knob { left: 23px; }

.ticket { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.seg { display: inline-flex; border-radius: 9px; overflow: hidden; border: 1px solid rgba(255,255,255,0.12); }
.seg button { border: none; background: transparent; color: #8a93a8; font-size: 13px; padding: 8px 16px; cursor: pointer; }
.seg button.on { background: #ff5470; color: #fff; }
.seg button.on.sell { background: #00e69a; color: #04121a; }
.ticket input { background: rgba(0,0,0,0.25); border: 1px solid rgba(255,255,255,0.1); border-radius: 8px; color: #f0f3fa; font-size: 13px; padding: 8px 10px; }
.t-code { width: 96px; font-family: "SF Mono", Consolas, monospace; }
.t-sh { width: 130px; }
.t-pr { width: 150px; }
.amt { font-size: 12px; color: #8a93a8; }
.oresult { margin-top: 12px; font-size: 12.5px; color: #00e69a; background: rgba(0,230,154,0.08); padding: 9px 12px; border-radius: 9px; }
.oresult.bad { color: #ff5470; background: rgba(255,84,112,0.08); }

.empty { color: #6b7384; font-size: 12.5px; }
.ptable { width: 100%; border-collapse: collapse; font-size: 12.5px; }
.ptable th { text-align: left; color: #6b7384; font-weight: 600; font-size: 11px; padding: 6px 8px; border-bottom: 1px solid rgba(255,255,255,0.08); }
.ptable td { padding: 9px 8px; border-bottom: 1px solid rgba(255,255,255,0.05); color: #c4cad6; }
.mono { font-family: "SF Mono", Consolas, monospace; }
.qbtns { display: flex; gap: 5px; }
.qbtns button { border: none; border-radius: 6px; font-size: 11px; padding: 3px 10px; cursor: pointer; background: rgba(255,84,112,0.16); color: #ff5470; }
.qbtns button.sell { background: rgba(0,230,154,0.16); color: #00e69a; }

.foot { color: #5c6378; font-size: 11.5px; margin-top: 24px; line-height: 1.7; }

.modal-mask { position: fixed; inset: 0; background: rgba(4,8,14,0.7); display: flex; align-items: center; justify-content: center; z-index: 100; backdrop-filter: blur(3px); }
.modal { width: 340px; background: #0d1320; border: 1px solid rgba(255,255,255,0.12); border-radius: 18px; overflow: hidden; box-shadow: 0 20px 60px rgba(0,0,0,0.5); }
.mhead { font-size: 16px; font-weight: 800; padding: 16px 20px; }
.mhead.buy { background: rgba(255,84,112,0.14); color: #ff5470; }
.mhead.sell { background: rgba(0,230,154,0.12); color: #00e69a; }
.mbody { padding: 16px 20px; }
.mrow { display: flex; justify-content: space-between; padding: 7px 0; font-size: 13.5px; }
.mrow span { color: #8a93a8; }
.mrow b { font-weight: 700; }
.mnote { font-size: 11.5px; color: #6b7384; margin-top: 10px; line-height: 1.5; }
.mbtns { display: flex; gap: 10px; padding: 0 20px 18px; }
.mbtns .btn { flex: 1; text-align: center; }
</style>
