// 「立即检查」运行状态：看板/策略页共用。
// 触发一次 runCheck → 监听 sentio:progress / sentio:done，驱动进度条与日志，
// 完成后回调各页自己的 reload。全局单例，避免重复监听。
import { ref } from "vue";
import {
  runCheck,
  onCheckProgress,
  onCheckDone,
  type SentioDone,
} from "./useSentio";

const running = ref(false);
const pct = ref(0);
const lines = ref<string[]>([]);
const lastMsg = ref("");
const ok = ref<boolean | null>(null);

let wired = false;
const doneCbs = new Set<(d: SentioDone) => void>();

async function wire() {
  if (wired) return;
  wired = true;
  await onCheckProgress((p) => {
    if (p.line) {
      lines.value = [...lines.value.slice(-40), p.line];
    }
    if (p.pct >= 0) pct.value = p.pct;
  });
  await onCheckDone((d) => {
    running.value = false;
    pct.value = d.ok ? 100 : pct.value;
    ok.value = d.ok;
    lastMsg.value = d.message;
    doneCbs.forEach((cb) => cb(d));
  });
}

export function useCheck() {
  async function start(codes?: string[]) {
    if (running.value) return;
    await wire();
    running.value = true;
    ok.value = null;
    pct.value = 1;
    lines.value = [];
    lastMsg.value = "正在启动采集与分析…";
    try {
      await runCheck(codes);
    } catch (e: any) {
      running.value = false;
      ok.value = false;
      lastMsg.value = e?.message || String(e);
    }
  }
  function onDone(cb: (d: SentioDone) => void) {
    doneCbs.add(cb);
    return () => doneCbs.delete(cb);
  }
  return { running, pct, lines, lastMsg, ok, start, onDone };
}
