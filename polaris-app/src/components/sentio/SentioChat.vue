<script setup lang="ts">
// 智投顾 · 对话包：一个干净的纯对话视图，只聊天、不启动项目/技能/工作流。
// 直接复用 Rust chat::chat_send 命令与 chat:stream 流式事件。
import { ref, onMounted, onUnmounted, nextTick } from "vue";
import { invoke, listen, isTauri, type ChatStreamEvent } from "../../tauri";

// 固定会话 id：append_message/get_messages 按此累积，给对话包多轮记忆 + 切走再回来能恢复历史。
const CONV_ID = "sentio-chat";

interface Message {
  role: "user" | "assistant";
  text: string;
  tools?: string[];
  error?: boolean;
}
interface StoredMessage {
  role: string;
  content: string;
}

const input = ref("");
const messages = ref<Message[]>([]);
const sending = ref(false);
const reqId = ref<string | null>(null);
const listEl = ref<HTMLDivElement | null>(null);
const errorText = ref("");
let unlisten: (() => void) | null = null;

function scrollBottom() {
  nextTick(() => {
    if (listEl.value) listEl.value.scrollTop = listEl.value.scrollHeight;
  });
}

async function send() {
  const prompt = input.value.trim();
  if (!prompt || sending.value) return;
  if (!isTauri) {
    errorText.value = "对话功能需在桌面端运行";
    return;
  }
  messages.value.push({ role: "user", text: prompt });
  input.value = "";
  sending.value = true;
  errorText.value = "";
  const assistantMsg: Message = { role: "assistant", text: "", tools: [] };
  messages.value.push(assistantMsg);
  scrollBottom();
  try {
    const id = await invoke<string>("chat_send", {
      args: {
        prompt,
        permissionMode: "auto_current", // 只聊当前选股问题，自动确认编辑
        useSandbox: false,
        useKb: false,
        skillIds: [],
        conversationId: CONV_ID,
      },
    });
    reqId.value = id;
  } catch (e) {
    sending.value = false;
    assistantMsg.error = true;
    assistantMsg.text = String(e);
  }
}

function onKeydown(e: KeyboardEvent) {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    send();
  }
}

onMounted(async () => {
  if (!isTauri) return;
  // 恢复历史：切到别的页再回来，对话不丢。
  try {
    const stored = await invoke<StoredMessage[]>("conv_get_messages", { conversationId: CONV_ID });
    messages.value = stored
      .filter((m) => m.role === "user" || m.role === "assistant")
      .map((m) => ({ role: m.role as "user" | "assistant", text: m.content }));
    scrollBottom();
  } catch {
    /* 无历史 / 非桌面端，忽略 */
  }
  unlisten = await listen<ChatStreamEvent>("chat:stream", (e) => {
    if (reqId.value && e.reqId !== reqId.value) return;
    const last = messages.value[messages.value.length - 1];
    if (!last || last.role !== "assistant") return;
    if (e.kind === "delta" && e.text) {
      last.text += e.text;
      scrollBottom();
    } else if (e.kind === "tool" && e.tool) {
      (last.tools ??= []).push(e.tool);
    } else if (e.kind === "error") {
      sending.value = false;
      last.error = true;
      last.text += e.text || "";
      scrollBottom();
    } else if (e.kind === "done") {
      sending.value = false;
      reqId.value = null;
    }
  });
});

onUnmounted(() => {
  unlisten?.();
});
</script>

<template>
  <div class="sentio-view">
    <div class="inner">
      <header class="head">
        <div>
          <div class="eyebrow">智投顾 · AI 智能选股</div>
          <h1>对话</h1>
        </div>
      </header>
      <p class="sub">
        直接问股票、策略、卖出时机或市场情绪。只保留对话本身，不触发项目/技能/工作流。
      </p>

      <div ref="listEl" class="msg-list">
        <div
          v-for="(m, i) in messages"
          :key="i"
          class="msg"
          :class="m.role"
        >
          <div class="bubble" :class="{ error: m.error }">
            <pre>{{ m.text }}</pre>
            <div v-if="m.tools?.length" class="tools">
              <span v-for="(t, idx) in m.tools" :key="idx" class="tool">🔧 {{ t }}</span>
            </div>
          </div>
        </div>
        <div v-if="sending && messages[messages.length - 1]?.role === 'assistant' && !messages[messages.length - 1].text" class="typing">
          <span></span><span></span><span></span>
        </div>
        <div v-if="!messages.length" class="empty">
          例如：「我持仓的 600519 现在要不要卖？」「最近 300750 什么时候卖最好？」
        </div>
      </div>

      <div class="input-area">
        <div v-if="errorText" class="err">{{ errorText }}</div>
        <div class="compose">
          <textarea
            v-model="input"
            :disabled="sending"
            rows="2"
            placeholder="输入问题，Shift+Enter 换行，Enter 发送"
            @keydown="onKeydown"
          />
          <button class="btn primary" :disabled="!input.trim() || sending" @click="send">
            {{ sending ? "思考中…" : "发送" }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.sentio-view {
  flex: 1; height: 100vh; overflow: hidden;
  background: #070a12;
  background-image: radial-gradient(circle at 15% 5%, rgba(91, 140, 255, 0.12), transparent 40%),
    radial-gradient(circle at 85% 12%, rgba(0, 224, 198, 0.1), transparent 42%);
  color: #f0f3fa;
  font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Microsoft YaHei", sans-serif;
  display: flex; flex-direction: column;
}
.inner { flex: 1; max-width: 960px; margin: 0 auto; width: 100%; padding: 28px 28px 16px; display: flex; flex-direction: column; box-sizing: border-box; }
.head { display: flex; align-items: flex-end; gap: 16px; margin-bottom: 6px; flex-shrink: 0; }
.eyebrow {
  font-size: 12px; font-weight: 600; letter-spacing: 0.06em;
  background: linear-gradient(120deg, #5b8cff, #00e0c6); -webkit-background-clip: text; background-clip: text; color: transparent;
}
h1 { font-size: 32px; font-weight: 800; letter-spacing: -0.02em; margin: 6px 0 0; }
.sub { color: #8a93a8; font-size: 13px; margin: 0 0 18px; line-height: 1.6; flex-shrink: 0; }

.msg-list { flex: 1; overflow-y: auto; display: flex; flex-direction: column; gap: 14px; padding-right: 4px; margin-bottom: 12px; }
.msg { display: flex; }
.msg.user { justify-content: flex-end; }
.msg.assistant { justify-content: flex-start; }
.bubble {
  max-width: 78%; border-radius: 14px; padding: 12px 16px; font-size: 14px; line-height: 1.65;
  background: rgba(255,255,255,0.08); color: #f0f3fa; word-break: break-word;
}
.user .bubble { background: linear-gradient(120deg, #5b8cff, #00e0c6); color: #04121a; }
.bubble.error { background: rgba(255,84,112,0.18); color: #ff9aaa; }
.bubble pre { margin: 0; white-space: pre-wrap; font-family: inherit; }
.tools { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }
.tool { font-size: 11px; color: #8a93a8; background: rgba(0,0,0,0.22); padding: 2px 8px; border-radius: 6px; }

.typing { display: flex; gap: 5px; padding: 10px 14px; width: 48px; }
.typing span { width: 7px; height: 7px; border-radius: 50%; background: #5b8cff; animation: bounce 1.2s infinite; }
.typing span:nth-child(2) { animation-delay: 0.15s; }
.typing span:nth-child(3) { animation-delay: 0.3s; }
@keyframes bounce { 0%,80%,100% { transform: translateY(0); } 40% { transform: translateY(-5px); } }

.empty { align-self: center; color: #5c6378; font-size: 13px; margin-top: auto; margin-bottom: auto; text-align: center; max-width: 420px; line-height: 1.7; }

.input-area { flex-shrink: 0; }
.err { color: #ff5470; font-size: 12px; margin-bottom: 6px; }
.compose { display: flex; gap: 10px; align-items: stretch; }
.compose textarea {
  flex: 1; resize: none; background: rgba(0,0,0,0.25); border: 1px solid rgba(255,255,255,0.1);
  border-radius: 12px; color: #f0f3fa; font-size: 14px; padding: 10px 14px; line-height: 1.55;
}
.compose textarea:focus { outline: none; border-color: #5b8cff; }
.compose textarea:disabled { opacity: 0.6; }
.btn { border: none; border-radius: 10px; font-size: 13px; padding: 0 20px; cursor: pointer; font-weight: 700; }
.btn.primary { background: linear-gradient(120deg, #5b8cff, #00e0c6); color: #04121a; }
.btn.primary:disabled { opacity: 0.45; cursor: default; }
</style>
