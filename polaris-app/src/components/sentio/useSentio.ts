// SENTIO 三视图共享：数据加载 + 颜色/档位/机会分等纯函数。
// 数据来自 data-pipeline 采集器写入的 public/sentio/*.json（Vite 映射到根路径）。
import { ref } from "vue";
import { invoke, listen, isTauri } from "../../tauri";

export interface Breakdown {
  热度H: number;
  资金F: number;
  文本情感S: number | null;
}
export interface StockRec {
  stock: string;
  code: string;
  name: string;
  sector: string;
  date: string;
  temperature: number;
  level: string;
  signal: string;
  breakdown: Breakdown;
  evidence: Record<string, string | number>;
  contrarian_note: string;
}
export interface Breadth {
  up?: number;
  down?: number;
  flat?: number;
  up_ratio?: number | null;
  north_flow?: number;
  indices?: { name: string; chg: number }[];
}
export interface Board {
  date: string;
  market_temp: number | null;
  market_level: string | null;
  market_signal: string | null;
  breadth: Breadth;
  reversal_alerts: number;
  overheated: string[];
  cold: string[];
  ranked: StockRec[];
  updated_at: string;
}

// ── 建议策略（strategy.json）数据模型 ──
export interface Radar {
  动量: number;
  趋势: number;
  资金: number;
  低波: number;
  情绪: number;
}
export interface Pick {
  code: string;
  name: string;
  sector: string;
  score: number;
  radar: Radar;
  temp: number;
  rsi: number;
  entry: number;
  stop: number;
  stop_pct: number;
  target: number;
  target_pct: number;
  weight: number;
  reason: string;
}
export interface BacktestPoint {
  date: string;
  strat: number;
  bench: number;
}
export interface Backtest {
  months: number;
  monthly_mean: number;
  monthly_std: number;
  total_return: number;
  cagr: number;
  vol_ann: number;
  sharpe: number;
  win_rate: number;
  max_drawdown: number;
  bench_total: number;
  curve: BacktestPoint[];
  params: Record<string, string | number>;
  sensitivity?: { lookback: number; topk: number; cagr: number }[];
}
export interface Mode {
  key: string;
  lookback: number;
  topk: number;
  desc: string;
  months: number;
  cagr: number;
  monthly_mean: number;
  monthly_std: number;
  win_rate: number;
  max_drawdown: number;
  sharpe: number;
  p_hit: number;
  p_lose: number;
}
export interface Achiever {
  achieved: boolean;
  config_text: string;
  freq: string;
  lookback: number;
  topk: number;
  leverage: number;
  monthly_mean: number;
  cagr: number;
  win_rate: number;
  max_drawdown: number;
  sharpe: number;
  p_hit: number;
  p_lose: number;
  months: number;
}
export interface TargetSummary {
  target_monthly: number;
  best_mode: string;
  best_monthly_mean: number;
  p_hit: number;
  p_lose: number;
  feasible: boolean;
  verdict: string;
  achiever: Achiever | null;
  honest_note: string;
}
export interface RankedRow {
  code: string;
  name: string;
  sector: string;
  score: number;
  mom60: number | null;
  rsi: number;
  temp: number;
}
export interface Strategy {
  date: string;
  universe: number;
  scored: number;
  failed: string[];
  weights: Record<string, number>;
  market: {
    cash_pct: number;
    stance: string;
    market_level: string | null;
    market_temp: number | null;
  };
  expectation: {
    base_monthly: number;
    range_low: number;
    range_high: number;
    invested_pct: number;
    note: string;
  } | null;
  modes: Mode[] | null;
  target: TargetSummary | null;
  picks: Pick[];
  ranked: RankedRow[];
  backtest: Backtest | null;
  disclaimer: string;
  updated_at: string;
}

// ── 斐波那契趋势策略（fib_strategy.json）数据模型 ──
export interface FibPooled {
  trades: number;
  win_rate: number;
  avg_win_pct: number;
  avg_loss_pct: number;
  payoff_ratio: number | null;
  profit_factor: number | null;
  expectancy_pct: number;
  expectancy_r: number;
  avg_bars: number;
  max_win_pct: number;
  max_loss_pct: number;
  kelly_pct: number;
  exit_reasons: Record<string, number>;
}
export interface FibPortfolioPoint {
  date: string;
  strat: number;
  bench: number;
}
export interface FibPortfolio {
  start: string;
  end: string;
  years: number;
  total_return: number;
  cagr: number;
  max_drawdown: number;
  vol_ann: number;
  sharpe: number;
  bench_total: number;
  bench_cagr: number;
  bench_mdd: number;
  excess: number;
  max_concurrent: number;
  curve: FibPortfolioPoint[];
}
export interface FibParamRow {
  k: number;
  m: number;
  trades: number;
  win_rate: number;
  payoff: number | null;
  profit_factor: number | null;
  expectancy_r: number;
}
export interface FibSlopeRow {
  require_slope: boolean;
  trades: number;
  win_rate: number;
  profit_factor: number | null;
  expectancy_r: number;
}
export interface FibVerdict {
  effective: boolean;
  headline: string;
  profit_factor?: number;
  expectancy_r?: number;
  excess?: number;
}
// 样本外(walk-forward OOS)诚实对照
export interface FibWalkForward {
  window: { train_months: number; test_months: number; step_months: number };
  span: string;
  is_pooled: FibPooled | null;
  oos_pooled: FibPooled | null;
  oos_portfolio: FibPortfolio | null;
  verdict: { effective: boolean; retention_pct: number; headline: string } | null;
}
// 市场态势(regime)快照
export interface FibRegime {
  symbol: string;
  date: string;
  close: number;
  exposure: number;
  label: string;
  detail: string;
  advice: string;
}
export interface FibHist {
  trades: number;
  win_rate: number;
  expectancy_r: number;
  profit_factor: number | null;
}
export interface FibCandidate {
  code: string;
  name: string;
  sector: string;
  state: "fresh_entry" | "holding" | "watch";
  reason: string;
  close: number;
  entry: number;
  fib_stop: number;
  fib_stop_pct: number;
  fib_k: number;
  trail_ma: number;
  trail_ma_label: string;
  dist_to_ma_pct: number;
  atr_pct: number;
  ema_gap_pct: number;
  suggest_pos_pct: number;
  above_slow: boolean;
  temp: number | null;
  hist: FibHist | null;
}
export interface FibStrategy {
  date: string;
  engine: string;
  universe: number;
  scanned: number;
  failed: string[];
  regime?: FibRegime | null;
  regime_gate?: boolean;
  config: {
    n1: number;
    n2: number;
    m: number;
    k: number;
    label: string;
    kelly_fraction: number;
    risk_per_trade: number;
    require_slope: boolean;
    cost_roundtrip: number;
  };
  validation: {
    pooled: FibPooled | null;
    portfolio: FibPortfolio | null;
    param_matrix: FibParamRow[];
    slope_compare: FibSlopeRow[];
    verdict: FibVerdict;
    walkforward?: FibWalkForward | null;
  };
  candidates: FibCandidate[];
  fresh_count: number;
  rules: { entry: string; stop: string; exit: string; size: string };
  disclaimer: string;
  updated_at: string;
}

// ── AI 催化剂否决层(ai_veto.json) ──
export interface AiVetoResult {
  code: string;
  name: string;
  veto: boolean;
  risk_score: number;
  catalyst_score: number;
  red_flags: string[];
  catalysts: string[];
  verdict: string;
  reason: string;
  news_count: number;
  source: string;
}
export interface AiVeto {
  date: string;
  mode: string;
  assessed: number;
  vetoed: string[];
  veto_count: number;
  keep: string[];
  results: AiVetoResult[];
  note: string;
  updated_at: string;
}
// ── 自选诊断(diagnose.json)数据模型 ──
export interface DiagFactors {
  close: number;
  ma20: number; ma60: number; ma120: number;
  ema21: number; ema55: number; ema34: number;
  atr_pct: number;
  rsi: number;
  r20: number; r60: number; r120: number;
  hi250: number; lo250: number; pos_in_range: number;
  vol_ann: number; vol_ratio: number | null;
  dist_ma20_pct: number; dist_ma60_pct: number;
  bull_align: boolean; above_ma60: boolean; below_ma120: boolean; ema_up: boolean;
}
export interface DiagStrategy {
  key: string; name: string; tier: string; fit: number; action: string; note: string;
}
export interface DiagHist {
  trades: number; win_rate: number; expectancy_r: number;
  profit_factor: number | null; avg_win_pct: number; avg_loss_pct: number;
}
export interface DiagProvenance {
  source: string; bars: number; first_date: string; last_date: string;
  last_close: number; verified: boolean;
}
export interface DiagHolding { cost: number | null; shares: number; pnl_pct: number; }
export interface BestExit {
  urgency: "now" | "soon" | "trail" | "hold" | "na";
  headline: string;
  trail_stop: number;
  hard_stop: number;
  take_profit_1: number | null;
  take_profit_2: number | null;
  triggers: string[];
  cost?: number;
  pnl_pct?: number;
  advice?: string;
}
export interface Diagnosis {
  code: string; name: string; sector: string;
  verdict: string; action: string;
  tier: "buy" | "hold" | "wait" | "warn" | "danger";
  timing: string;
  entry: number | null; stop: number; stop_pct: number;
  target1: number | null; target2: number | null; struct_target: number; upside_pct: number | null;
  confidence: number;
  factors: DiagFactors;
  fib_signal: FibCandidate | null;
  strategies: DiagStrategy[];
  hist: DiagHist | null;
  best_exit: BestExit | null;
  holding: DiagHolding | null;
  position_note: string | null;
  provenance: DiagProvenance;
  error?: string;
}
export interface Diagnose {
  date: string;
  engine: string;
  count: number;
  requested: string[];
  failed: { code: string; error: string }[];
  config: { label: string; k: number; n1: number; n2: number; m: number };
  diagnoses: Diagnosis[];
  actions_legend: Record<string, string>;
  disclaimer: string;
  updated_at: string;
}

// 统一读取脚本产出的前端 JSON。
// 桌面端优先走 Rust `sentio_read`：打包态脚本写到 app-data 可写副本，前端 fetch('/sentio/..') 只能拿到
// 安装包里的旧副本，故必须改读可写目录的最新产物；失败/非桌面端再回退 fetch（开发态 Vite / Web 壳）。
async function readSentio<T>(name: string): Promise<T | null> {
  if (isTauri) {
    try {
      const txt = await invoke<string | null>("sentio_read", { name });
      if (txt) return JSON.parse(txt) as T;
    } catch {
      /* 落到 fetch 回退 */
    }
  }
  try {
    const base = import.meta.env.BASE_URL || "/";
    const r = await fetch(`${base}sentio/${name}?t=${Date.now()}`);
    if (!r.ok) return null;
    return (await r.json()) as T;
  } catch {
    return null;
  }
}

export async function loadAiVeto(): Promise<AiVeto | null> {
  return readSentio<AiVeto>("ai_veto.json");
}

// ── 系统健康监控(monitor_status.json) ──
export interface MonitorCheck {
  sev: "ok" | "warn" | "err";
  msg: string;
  detail: Record<string, unknown>;
}
export interface MonitorStatus {
  overall: string;
  overall_sev: "ok" | "warn" | "err";
  checks: Record<string, MonitorCheck>;
  updated_at: string;
}
export async function loadMonitor(): Promise<MonitorStatus | null> {
  return readSentio<MonitorStatus>("monitor_status.json");
}

export async function loadFib(): Promise<FibStrategy | null> {
  return readSentio<FibStrategy>("fib_strategy.json");
}

/** 触发一次斐波那契选股（取价+回测+寻优+今日选股）。进度走 fib:progress / fib:done。 */
export async function runFib(codes?: string[], aiLlm?: boolean): Promise<string> {
  if (!isTauri) {
    throw new Error("「斐波检查」需在桌面端运行（本机 Python 取价回测）");
  }
  // aiLlm=true → 后端开 SENTIO_AI_LLM，AI 排雷层走左下角「供应商坞」当前选中的 API。
  const args: Record<string, unknown> = {};
  if (codes && codes.length) args.codes = codes;
  if (aiLlm) args.aiLlm = true;
  return invoke<string>("fib_run", args);
}
export function onFibProgress(cb: (p: SentioProgress) => void) {
  return listen<SentioProgress>("fib:progress", cb);
}
export function onFibDone(cb: (d: SentioDone) => void) {
  return listen<SentioDone>("fib:done", cb);
}

// ── 自选诊断：读结果 / 触发诊断 / 进度事件 ──
export async function loadDiagnose(): Promise<Diagnose | null> {
  return readSentio<Diagnose>("diagnose.json");
}
/** 触发一次自选诊断。codes 为空 = 诊断 my_watchlist.json。进度走 diag:progress / diag:done。 */
export async function runDiag(codes?: string[], aiLlm?: boolean): Promise<string> {
  if (!isTauri) {
    throw new Error("「自选诊断」需在桌面端运行（本机 Python 取真实行情）");
  }
  const args: Record<string, unknown> = {};
  if (codes && codes.length) args.codes = codes;
  if (aiLlm) args.aiLlm = true;
  return invoke<string>("diag_run", args);
}
export function onDiagProgress(cb: (p: SentioProgress) => void) {
  return listen<SentioProgress>("diag:progress", cb);
}
export function onDiagDone(cb: (d: SentioDone) => void) {
  return listen<SentioDone>("diag:done", cb);
}

// ── 自选股 / 持仓配置：读写（账户管理基座）──
export interface MyStock { code: string; name?: string; sector?: string; }
export interface Holding { code: string; cost?: number | null; shares?: number; }
async function readConfig<T>(name: string): Promise<T | null> {
  if (!isTauri) return null;
  try {
    const txt = await invoke<string | null>("diag_config_read", { name });
    if (txt) return JSON.parse(txt) as T;
  } catch {
    /* ignore */
  }
  return null;
}
async function writeConfig(name: string, obj: unknown): Promise<void> {
  if (!isTauri) throw new Error("需在桌面端保存");
  await invoke("diag_config_write", { name, content: JSON.stringify(obj, null, 2) });
}
export async function loadMyWatchlist(): Promise<MyStock[]> {
  const d = await readConfig<{ stocks: MyStock[] }>("my_watchlist.json");
  return d?.stocks ?? [];
}
export async function saveMyWatchlist(stocks: MyStock[]): Promise<void> {
  await writeConfig("my_watchlist.json", { stocks });
}
export async function loadHoldings(): Promise<Holding[]> {
  const d = await readConfig<{ positions: Holding[] }>("holdings.json");
  return d?.positions ?? [];
}
export async function saveHoldings(positions: Holding[]): Promise<void> {
  await writeConfig("holdings.json", { positions });
}

// ── 用户自定义信源：让用户登记自己想关注的渠道，与内置信源目录合并展示 ──
export interface UserSource {
  name: string;
  provider: string;
  api?: string;
  feeds?: string;
  method?: string;
  note?: string;
}
export async function loadUserSources(): Promise<UserSource[]> {
  const d = await readConfig<{ sources: UserSource[] }>("user_sources.json");
  return d?.sources ?? [];
}
export async function saveUserSources(sources: UserSource[]): Promise<void> {
  await writeConfig("user_sources.json", { sources });
}

// ── 券商对接 / 账户管理(easytrader) ──
export interface AcctBalance { cash: number; market_value: number; total: number; frozen: number; }
export interface AcctPosition {
  code: string; name: string; shares: number; cost: number; price: number;
  market_value: number; pnl: number; pnl_pct: number;
}
export interface RiskLimits { per_order: number; per_day: number; max_pos_pct: number; }
export interface Account {
  ok: boolean; adapter: string; connected: boolean; auto_trade: boolean;
  limits: RiskLimits;
  balance?: AcctBalance; positions?: AcctPosition[]; day_spent?: number;
  error?: string; updated_at: string;
}
export interface BrokerConfig {
  adapter: string; auto_trade: boolean; limits: RiskLimits;
  easytrader: { broker: string; exe_path: string; config_path: string };
  sim_start_cash: number;
}
export interface OrderResult {
  ok: boolean; msg?: string; blocked?: string;
  action: string; code: string; name?: string; shares: number; price: number; amount: number;
}
export const DEFAULT_BROKER_CONFIG: BrokerConfig = {
  adapter: "sim", auto_trade: false,
  limits: { per_order: 50000, per_day: 200000, max_pos_pct: 25 },
  easytrader: { broker: "universal_client", exe_path: "", config_path: "" },
  sim_start_cash: 1000000,
};

async function brokerCmd<T>(args: string[]): Promise<T> {
  if (!isTauri) throw new Error("账户/券商功能需在桌面端运行");
  const txt = await invoke<string>("broker_cmd", { args });
  return JSON.parse(txt) as T;
}
export async function loadAccount(): Promise<Account | null> {
  return readSentio<Account>("account.json");
}
export async function brokerStatus(): Promise<Account> {
  return brokerCmd<Account>(["status"]);
}
export async function brokerSync(): Promise<{ ok: boolean; synced: number; account: Account }> {
  return brokerCmd<{ ok: boolean; synced: number; account: Account }>(["sync"]);
}
/** 下单：单笔模式由前端「确认后」调用；后端再过风控三闸，blocked 时返回拦截原因。 */
export async function brokerOrder(
  action: "BUY" | "SELL", code: string, shares: number, price?: number
): Promise<OrderResult> {
  const args = ["order", action, code, String(shares)];
  if (price && price > 0) args.push(String(price));
  return brokerCmd<OrderResult>(args);
}
export async function brokerResetSim(): Promise<{ ok: boolean; msg: string }> {
  return brokerCmd<{ ok: boolean; msg: string }>(["reset-sim"]);
}

// ── 一键连接：渠道探测 / 连接 / 东财授权 ──
export interface Channel {
  key: string;
  name: string;
  kind: "sim" | "eastmoney_web" | "easytrader";
  hint: string;
  ready: boolean;
  exe?: string;
  candidates?: string[];
  can_authorize?: boolean;
  authorized?: boolean;
}
export interface DetectResult {
  ok: boolean;
  channels: Channel[];
  xiadan_found: string[];
  selenium: boolean;
}
export interface ConnectResult {
  ok: boolean;
  channel: string;
  connected: boolean;
  msg?: string;
  error?: string;
  need?: "exe" | "authorize";
  candidates?: string[];
  account?: Account;
}
/** 探测本机可连接的渠道（已装客户端/东财授权态）。耗时操作（扫盘+注册表）。 */
export async function brokerDetect(): Promise<DetectResult> {
  return brokerCmd<DetectResult>(["detect"]);
}
/** 一键连接某渠道；easytrader 渠道可带 exe 路径。 */
export async function brokerConnect(channel: string, exe?: string): Promise<ConnectResult> {
  const args = ["connect", channel];
  if (exe) args.push(exe);
  return brokerCmd<ConnectResult>(args);
}
/** 东方财富一键授权：弹出官方登录页，登录完成后取会话并连接。会阻塞到登录完成/超时。 */
export async function brokerEastmoneyAuth(): Promise<ConnectResult & { need?: string }> {
  return brokerCmd<ConnectResult & { need?: string }>(["eastmoney-auth"]);
}
export async function brokerEastmoneyLogout(): Promise<{ ok: boolean; msg: string }> {
  return brokerCmd<{ ok: boolean; msg: string }>(["eastmoney-logout"]);
}
export async function loadBrokerConfig(): Promise<BrokerConfig> {
  const d = await readConfig<BrokerConfig>("broker_config.json");
  return { ...DEFAULT_BROKER_CONFIG, ...(d ?? {}),
    limits: { ...DEFAULT_BROKER_CONFIG.limits, ...(d?.limits ?? {}) },
    easytrader: { ...DEFAULT_BROKER_CONFIG.easytrader, ...(d?.easytrader ?? {}) } };
}
export async function saveBrokerConfig(cfg: BrokerConfig): Promise<void> {
  await writeConfig("broker_config.json", cfg);
}

export async function loadBoard(): Promise<Board | null> {
  return readSentio<Board>("board.json");
}

export async function loadStocks(): Promise<StockRec[]> {
  return (await readSentio<StockRec[]>("sentiment_latest.json")) ?? [];
}

// 温度 → 颜色（与 PRD 色板一致：过热红 / 偏热金 / 中性灰 / 偏冷蓝 / 冰点绿）
export function tempColor(t: number): string {
  if (t >= 80) return "#ff5470";
  if (t >= 65) return "#ffcf6b";
  if (t <= 20) return "#00e69a";
  if (t <= 35) return "#5b8cff";
  return "#8a93a8";
}

export function levelColor(level: string): string {
  return (
    {
      过热: "#ff5470",
      偏热: "#ffcf6b",
      中性: "#8a93a8",
      偏冷: "#5b8cff",
      冰点: "#00e69a",
    }[level] || "#8a93a8"
  );
}

// 反向「机会分」0-100：资金净流入越强、情绪越不过热 → 机会越大（被冷落但资金回流=金机会）
export function opportunityScore(r: StockRec): number {
  const f = r.breakdown.资金F ?? 50;
  return Math.round(f * 0.5 + (100 - r.temperature) * 0.5);
}

// 门派契合（极简启发式，仅作展示）：按情绪/资金给一个最契合门派标签
export function schoolFit(r: StockRec): string {
  const t = r.temperature;
  const f = r.breakdown.资金F ?? 50;
  if (t <= 35) return "价值派 · 低估安全边际";
  if (f >= 60 && t < 75) return "趋势派 · 资金突破";
  if (t >= 80) return "反向派 · 过热预警";
  if (f >= 55) return "成长派 · 资金温和";
  return "稳健派 · 中性观望";
}

export const ALL_SECTORS = [
  "金融",
  "新能源",
  "电池",
  "AI",
  "半导体",
  "医药",
  "消费",
  "军工",
  "机器人",
  "算力",
];

// 操作建议（按档位映射，PRD 个股报告口径）
export function adviceOf(r: StockRec): {
  verdict: string;
  action: string;
  position: string;
  stop: string;
  target: string;
} {
  const t = r.temperature;
  if (t >= 80)
    return {
      verdict: "观望偏空 · 不追高",
      action: "散户狂热，回踩关键均线再考虑，不追高",
      position: "单笔风险 ≤ 2%，仓位收紧",
      stop: "买点下方 7–8%（欧奈尔铁律）",
      target: "已过热，奔 10–15% 即移动止盈",
    };
  if (t >= 65)
    return {
      verdict: "持有偏多 · 收紧止损",
      action: "情绪升温，持有可顺势，新仓控量",
      position: "单笔风险 ≤ 2%",
      stop: "买点下方 7–8%",
      target: "奔 20–25%，移动止盈",
    };
  if (t <= 20)
    return {
      verdict: "关注偏多 · 左侧",
      action: "恐慌见底信号，分批左侧建仓",
      position: "单笔风险 ≤ 2%，分批",
      stop: "买点下方 8–10%",
      target: "情绪修复至中性即减",
    };
  if (t <= 35)
    return {
      verdict: "关注 · 留意修复",
      action: "情绪低迷，等资金回流确认再进",
      position: "轻仓试探",
      stop: "买点下方 8%",
      target: "奔 15–20%",
    };
  return {
    verdict: "中性 · 结合基本面",
    action: "情绪中性，结合基本面/技术面定夺",
    position: "单笔风险 ≤ 2%",
    stop: "买点下方 7–8%",
    target: "奔 20%",
  };
}

// 简单的「最近一次加载时间」展示
export function useUpdatedAt() {
  return ref<string>("");
}

export async function loadStrategy(): Promise<Strategy | null> {
  return readSentio<Strategy>("strategy.json");
}

// ── 「立即检查」：调起本机 python 采集 + 多因子策略 + 回测 ──
export interface SentioProgress {
  line: string;
  pct: number;
}
export interface SentioDone {
  ok: boolean;
  code: number;
  message: string;
}

/** 触发一次采集分析。返回 "started"；进度/结果走事件。非 Tauri 环境抛错。 */
export async function runCheck(codes?: string[], aiLlm?: boolean): Promise<string> {
  if (!isTauri) {
    throw new Error("「立即检查」需在桌面端运行（本机 Python 采集）");
  }
  const args: Record<string, unknown> = {};
  if (codes && codes.length) args.codes = codes;
  if (aiLlm) args.aiLlm = true;
  return invoke<string>("sentio_run", args);
}

export function onCheckProgress(cb: (p: SentioProgress) => void) {
  return listen<SentioProgress>("sentio:progress", cb);
}
export function onCheckDone(cb: (d: SentioDone) => void) {
  return listen<SentioDone>("sentio:done", cb);
}

// 评分 → 颜色（达人评分 0-100：高分暖金，低分冷蓝）
export function scoreColor(s: number): string {
  if (s >= 80) return "#ffcf6b";
  if (s >= 60) return "#00e69a";
  if (s >= 40) return "#33e0ff";
  return "#8a93a8";
}
