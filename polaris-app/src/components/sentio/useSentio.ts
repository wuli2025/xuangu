// SENTIO 三视图共享：数据加载 + 颜色/档位/机会分等纯函数。
// 数据来自 data-pipeline 采集器写入的 public/sentio/*.json（Vite 映射到根路径）。
import { ref } from "vue";

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

const BASE = import.meta.env.BASE_URL || "/";

export async function loadBoard(): Promise<Board | null> {
  try {
    const r = await fetch(`${BASE}sentio/board.json?t=${Date.now()}`);
    if (!r.ok) return null;
    return (await r.json()) as Board;
  } catch {
    return null;
  }
}

export async function loadStocks(): Promise<StockRec[]> {
  try {
    const r = await fetch(`${BASE}sentio/sentiment_latest.json?t=${Date.now()}`);
    if (!r.ok) return [];
    return (await r.json()) as StockRec[];
  } catch {
    return [];
  }
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
