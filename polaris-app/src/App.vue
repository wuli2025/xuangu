<script setup lang="ts">
import { computed, onMounted, defineAsyncComponent } from "vue";
// ── 常驻 / 首屏关键：静态导入（启动即需，进启动主包）──
import Sidebar from "./components/Sidebar.vue";
import ChatPanel from "./components/ChatPanel.vue";
import EnvDoctor from "./components/EnvDoctor.vue"; // env_doctor 视图
// ── 非首屏视图：懒加载，切到对应视图时才拉各自 chunk ──
const Settings = defineAsyncComponent(() => import("./components/Settings.vue"));
const AddProviderModal = defineAsyncComponent(() => import("./components/AddProviderModal.vue"));
const McpConfigModal = defineAsyncComponent(() => import("./components/McpConfigModal.vue"));
const WorkflowPackModal = defineAsyncComponent(() => import("./components/WorkflowPackModal.vue"));
const UsageBoard = defineAsyncComponent(() => import("./components/UsageBoard.vue"));
const UpdatePanel = defineAsyncComponent(() => import("./components/UpdatePanel.vue"));
// ── 智投顾三屏：舆情看板 / 选股雷达 / 个股报告 ──
const SentioBoard = defineAsyncComponent(() => import("./components/sentio/SentioBoard.vue"));
const SentioRadar = defineAsyncComponent(() => import("./components/sentio/SentioRadar.vue"));
const SentioStrategy = defineAsyncComponent(() => import("./components/sentio/SentioStrategy.vue"));
const SentioFib = defineAsyncComponent(() => import("./components/sentio/SentioFib.vue"));
const SentioDiagnose = defineAsyncComponent(() => import("./components/sentio/SentioDiagnose.vue"));
const SentioReport = defineAsyncComponent(() => import("./components/sentio/SentioReport.vue"));
const SentioSources = defineAsyncComponent(() => import("./components/sentio/SentioSources.vue"));
import { useAppStore } from "./stores/app";
import { useProvidersStore } from "./stores/providers";
import { useChatStore } from "./stores/chat";
import { useWorkflowsStore } from "./stores/workflows";
import { checkForUpdate } from "./composables/useUpdater";

const app = useAppStore();
const providers = useProvidersStore();
const chatStore = useChatStore();
const workflows = useWorkflowsStore();

const mountedView = computed(() => app.view);

// 对话后台引擎注册一次流式监听（盯盘/报告生成调用）。
// 智投顾：无进场动画、无启动自动更新检查（避免无 release 时报错），开窗直达主界面。
onMounted(() => {
  chatStore.init();
  // 开机静默检查远程更新（GitHub Releases / latest.json）。无网络/无 release/非 Tauri 时静默吞掉，
  // 发现新版本由 Rust 状态机推送，UpdateBanner/UpdatePanel 自动提示「有更新待装」。
  checkForUpdate();
  // URL 深链：?view=fib 直达对应视图（便于直接打开某屏 / 截图 / 外部跳转）
  try {
    const v = new URLSearchParams(location.search).get("view");
    const allowed = ["board", "radar", "strategy", "fib", "diagnose", "report", "sources", "env_doctor", "update", "settings"];
    if (v && allowed.includes(v)) app.view = v as typeof app.view;
  } catch {
    /* ignore */
  }
});

// 右侧抽屉已移除，主区两列布局：侧栏 + 主内容。
const layoutCols = computed(() => `${app.sidebarWidth}px 1fr`);
</script>

<template>
  <div class="shell" :style="{ gridTemplateColumns: layoutCols }">
    <Sidebar />
    <main class="main">
      <SentioBoard v-if="mountedView === 'board'" @open-report="app.openReport" />
      <SentioRadar v-else-if="mountedView === 'radar'" @open-report="app.openReport" />
      <SentioStrategy v-else-if="mountedView === 'strategy'" @open-report="app.openReport" />
      <SentioFib v-else-if="mountedView === 'fib'" @open-report="app.openReport" />
      <SentioDiagnose v-else-if="mountedView === 'diagnose'" @open-report="app.openReport" />
      <SentioReport v-else-if="mountedView === 'report'" />
      <SentioSources v-else-if="mountedView === 'sources'" />
      <ChatPanel v-else-if="mountedView === 'chat'" />
      <EnvDoctor v-else-if="mountedView === 'env_doctor'" />
      <UpdatePanel v-else-if="mountedView === 'update'" />
      <Settings v-else-if="mountedView === 'settings'" />
    </main>

    <AddProviderModal v-if="providers.showAddModal" />
    <WorkflowPackModal v-if="workflows.editorOpen" />
    <UsageBoard v-if="providers.showUsageBoard" />

    <!-- MCP 配置对话框（触发器已移到 Sidebar 导航栏下方） -->
    <McpConfigModal v-if="app.showMcpModal" @close="app.showMcpModal = false" />
  </div>
</template>

<style scoped>
.shell {
  height: 100vh;
  display: grid;
  transition: grid-template-columns 180ms ease;
}
.main {
  position: relative;
  height: 100vh;
  overflow: hidden;
  background: var(--bg-chat);
  display: flex;
  flex-direction: column;
}
.placeholder {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--muted);
  font-family: var(--serif);
  font-size: 14px;
  letter-spacing: 2px;
}
</style>
