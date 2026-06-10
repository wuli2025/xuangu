import { defineStore } from "pinia";
import { ref } from "vue";
import {
  chat as chatApi,
  convApi,
  listen,
  type ChatStreamEvent,
  type AttachedFile,
  type PermissionMode,
} from "../tauri";
import { useAppStore } from "./app";
import { useSessionsStore } from "../features/coworker/stores/sessions";

export interface Bubble {
  role: "user" | "assistant" | "tool";
  text: string;
  tool?: string;
  /** 本条 assistant 消息生成的成品文件（绝对路径，正斜杠） */
  artifacts?: string[];
  /** 本条 user 消息携带的上传附件 */
  files?: AttachedFile[];
}

/** 解析正文里夹带的产物清单 marker，返回剥离 marker 后的纯文本 + 路径数组 */
export function parseArtifacts(content: string): {
  text: string;
  artifacts: string[];
} {
  const m = content.match(/<!--POLARIS_ARTIFACTS:(\[[\s\S]*?\])-->/);
  if (!m) return { text: content, artifacts: [] };
  let arr: string[] = [];
  try {
    arr = JSON.parse(m[1]);
  } catch {
    arr = [];
  }
  const text = content.replace(m[0], "").trimEnd();
  return { text, artifacts: arr };
}

/**
 * 对话运行时 store —— 多开的核心。
 *
 * 每个对话各自维护 bubbles / sending / reqId；流式事件在 app 级监听一次，
 * 按 `conversationId` 路由进各自缓冲。这样切到任意对话都能看到它的实时进度，
 * 多个任务可同时在后台流式推进（互不干扰），切走也不会"停"。
 */
export const useChatStore = defineStore("chatRuntime", () => {
  const byConv = ref<Record<string, Bubble[]>>({});
  const reqByConv = ref<Record<string, string>>({});
  const sendingByConv = ref<Record<string, boolean>>({});
  const loadedByConv = ref<Record<string, boolean>>({});
  // 本地「最近活跃时间」：发送/结束时打点。后端 updatedAt 在会话内不变，
  // 用它让刚交互过的对话在侧栏冒泡到最上（仿 Codex 最近对话置顶）。
  const activeAtByConv = ref<Record<string, number>>({});
  // 最近一轮注入的估算 input token（后端 meta 事件给出）。分批编排据此自适应批量。
  const tokensByConv = ref<Record<string, number>>({});
  // 等待某对话「本轮 done」的 resolver 队列（分批编排循环逐轮 await）。
  const doneWaiters: Record<string, Array<() => void>> = {};
  let started = false;

  /** 等到指定对话「本轮跑完(done)」。当前不在发送态则立即兑现。 */
  function waitForDone(convId: string): Promise<void> {
    if (!sendingByConv.value[convId]) return Promise.resolve();
    return new Promise<void>((resolve) => {
      (doneWaiters[convId] ??= []).push(resolve);
    });
  }
  /** 唤醒并清空某对话的 done 等待队列。done / cancel / 发送失败都必须调用,
   *  否则正在 await waitForDone 的分批编排循环会永久挂起(进度条卡死)。 */
  function wakeWaiters(convId: string) {
    const waiters = doneWaiters[convId];
    if (waiters && waiters.length) {
      doneWaiters[convId] = [];
      for (const w of waiters) w();
    }
  }
  function inputTokens(convId: string | null): number {
    if (!convId) return 0;
    return tokensByConv.value[convId] ?? 0;
  }

  function bubblesFor(convId: string | null): Bubble[] {
    if (!convId) return [];
    return byConv.value[convId] ?? [];
  }
  function isSending(convId: string | null): boolean {
    return !!(convId && sendingByConv.value[convId]);
  }
  function activityAt(convId: string | null): number {
    if (!convId) return 0;
    return activeAtByConv.value[convId] ?? 0;
  }
  function touchActivity(convId: string) {
    if (!convId) return;
    activeAtByConv.value[convId] = Date.now();
  }
  function ensureArr(convId: string): Bubble[] {
    if (!byConv.value[convId]) byConv.value[convId] = [];
    return byConv.value[convId];
  }
  function pushBubble(convId: string, b: Bubble) {
    ensureArr(convId).push(b);
  }

  async function loadHistory(convId: string | null, force = false) {
    if (!convId) return;
    // 正在运行的对话别用历史覆盖实时气泡
    if (sendingByConv.value[convId]) return;
    if (loadedByConv.value[convId] && !force) return;
    try {
      const msgs = await convApi.getMessages(convId);
      byConv.value[convId] = msgs.map((m) => {
        if (m.role === "assistant") {
          const { text, artifacts } = parseArtifacts(m.content);
          return { role: m.role, text, artifacts } as Bubble;
        }
        return { role: m.role, text: m.content } as Bubble;
      });
      loadedByConv.value[convId] = true;
    } catch {
      byConv.value[convId] = [];
    }
  }

  /** 发送一条消息：推入 user 气泡 + 调后端，记录 reqId/sending（不阻塞，多开） */
  async function send(
    convId: string,
    prompt: string,
    displayText: string,
    files: AttachedFile[] | undefined,
    opts: {
      permissionMode: PermissionMode;
      skillIds: string[];
      goal?: string;
      dynamicWorkflow?: boolean;
      useKb?: boolean;
      batchBuild?: boolean;
      batchSize?: number;
    }
  ) {
    const sessions = useSessionsStore();
    const arr = ensureArr(convId);
    arr.push({
      role: "user",
      text: displayText,
      files: files && files.length ? files : undefined,
    });
    sendingByConv.value[convId] = true;
    touchActivity(convId);
    sessions.start(convId, displayText.slice(0, 18));
    try {
      const reqId = await chatApi.send({
        prompt,
        permissionMode: opts.permissionMode,
        skillIds: opts.skillIds,
        goal: opts.goal,
        dynamicWorkflow: opts.dynamicWorkflow,
        useKb: opts.useKb,
        batchBuild: opts.batchBuild,
        batchSize: opts.batchSize,
        conversationId: convId,
      });
      reqByConv.value[convId] = reqId;
    } catch (e: any) {
      arr.push({ role: "assistant", text: `[发送失败] ${e?.message ?? e}` });
      sendingByConv.value[convId] = false;
      sessions.finish(convId);
      wakeWaiters(convId); // 否则分批循环 await 永挂
    }
  }

  async function cancel(convId: string | null) {
    if (!convId) return;
    const sessions = useSessionsStore();
    const req = reqByConv.value[convId];
    if (req) {
      try {
        await chatApi.cancel(req);
      } catch {
        /* ignore */
      }
    }
    sendingByConv.value[convId] = false;
    delete reqByConv.value[convId];
    touchActivity(convId);
    sessions.finish(convId);
    wakeWaiters(convId); // 取消后唤醒分批循环, 让它看到 !isRunning 自行收尾
  }

  /** app 级初始化：注册一次流式监听，按 conversationId 路由进各自缓冲 */
  async function init() {
    if (started) return;
    started = true;
    await listen<ChatStreamEvent>("chat:stream", (ev) => {
      const cid = ev.conversationId;
      if (!cid) return; // 无会话归属的事件无法路由（理论上不会出现）
      const arr = ensureArr(cid);
      if (ev.kind === "delta") {
        const last = arr[arr.length - 1];
        if (last && last.role === "assistant") last.text += ev.text ?? "";
        else arr.push({ role: "assistant", text: ev.text ?? "" });
      } else if (ev.kind === "tool") {
        arr.push({
          role: "tool",
          text: `调用工具:${ev.tool ?? "(unknown)"}`,
          tool: ev.tool,
        });
      } else if (ev.kind === "artifact") {
        const path = ev.text;
        if (path) {
          let target: Bubble | undefined;
          for (let i = arr.length - 1; i >= 0; i--) {
            if (arr[i].role === "assistant") {
              target = arr[i];
              break;
            }
          }
          if (!target) {
            target = { role: "assistant", text: "", artifacts: [] };
            arr.push(target);
          }
          if (!target.artifacts) target.artifacts = [];
          if (!target.artifacts.includes(path)) target.artifacts.push(path);
        }
      } else if (ev.kind === "meta") {
        // 上下文预算自检：后端估算的本轮 input token 数（纯数字文本）
        const n = parseInt(ev.text ?? "", 10);
        if (!Number.isNaN(n)) tokensByConv.value[cid] = n;
      } else if (ev.kind === "error") {
        // stderr 行 / 退出错误：仅展示，不作为终态（终态由 done 处理）
        arr.push({ role: "assistant", text: `[错误] ${ev.text ?? ""}` });
      } else if (ev.kind === "done") {
        // 终态：结束运行态 + 工位会话；若用户不在看该对话则打墨蓝未读点
        sendingByConv.value[cid] = false;
        delete reqByConv.value[cid];
        touchActivity(cid);
        // 本轮的实时气泡(含 [错误] 等未持久化的合成气泡)即为该对话的权威视图,
        // 标记 loaded 防止之后切回时 loadHistory 用后端副本覆盖、丢掉这些气泡。
        loadedByConv.value[cid] = true;
        const app = useAppStore();
        const sessions = useSessionsStore();
        sessions.finish(cid);
        app.markUnread(cid);
        // 唤醒分批编排循环：本轮已结束，可读清单决定续不续
        wakeWaiters(cid);
      }
    });
  }

  return {
    byConv,
    bubblesFor,
    isSending,
    activityAt,
    pushBubble,
    loadHistory,
    send,
    cancel,
    init,
    waitForDone,
    inputTokens,
  };
});
