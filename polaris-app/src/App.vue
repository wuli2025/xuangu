<script setup lang="ts">
import { computed, ref, watch, onMounted, defineAsyncComponent } from "vue";
// ── 常驻 / 首屏关键：静态导入（启动即需，进启动主包）──
import Sidebar from "./components/Sidebar.vue";
import ViewLoader from "./components/ViewLoader.vue";
import RightDrawer from "./components/RightDrawer.vue";
import ChatPanel from "./components/ChatPanel.vue";
import EnvDoctor from "./components/EnvDoctor.vue"; // env_doctor 视图
import UpdateBanner from "./components/UpdateBanner.vue";
// ── 重 / 非首屏视图：懒加载，切到对应视图时才拉各自 chunk ──
// 把 cytoscape(图谱) + 4 套工坊 + 各面板/弹层(合计上万行)从启动主包挪走 → 开窗快、首屏不卡。
const Automation = defineAsyncComponent(() => import("./components/Automation.vue"));
const AutomationModal = defineAsyncComponent(() => import("./components/AutomationModal.vue"));
const Settings = defineAsyncComponent(() => import("./components/Settings.vue"));
const AddProviderModal = defineAsyncComponent(() => import("./components/AddProviderModal.vue"));
const McpConfigModal = defineAsyncComponent(() => import("./components/McpConfigModal.vue"));
const WorkflowPackModal = defineAsyncComponent(() => import("./components/WorkflowPackModal.vue"));
const UsageBoard = defineAsyncComponent(() => import("./components/UsageBoard.vue"));
const UpdatePanel = defineAsyncComponent(() => import("./components/UpdatePanel.vue"));
// ── SENTIO 三屏：舆情看板 / 选股雷达 / 个股报告 ──
const SentioBoard = defineAsyncComponent(() => import("./components/sentio/SentioBoard.vue"));
const SentioRadar = defineAsyncComponent(() => import("./components/sentio/SentioRadar.vue"));
const SentioReport = defineAsyncComponent(() => import("./components/sentio/SentioReport.vue"));
import { checkForUpdate } from "./composables/useUpdater";
import { useAppStore, type ViewKey } from "./stores/app";
import { useArtifactsStore } from "./stores/artifacts";
import { useProvidersStore } from "./stores/providers";
import { useChatStore } from "./stores/chat";
import { useWorkflowsStore } from "./stores/workflows";
import { useAutomationStore } from "./stores/automation";

const app = useAppStore();
const artifacts = useArtifactsStore();
const providers = useProvidersStore();
const chatStore = useChatStore();
const workflows = useWorkflowsStore();
const automation = useAutomationStore();

// 智投顾：重型视图(图谱/沙箱)已移除，无需"点击即缓冲"加载条机制，直接按 app.view 渲染。
const mountedView = computed(() => app.view);

// 多开核心：app 级注册一次流式监听，任意对话的事件都按 conversationId 路由进各自缓冲，
// 这样切走/未挂载 ChatPanel 时后台任务仍持续流式推进、完成有提醒。
// 智投顾：已去除 splash/onboarding/env 门禁三层进场动画，开窗直达主界面，挂载后静默查更新。
onMounted(() => {
  chatStore.init();
  checkForUpdate();
});

// 预览成品文件时把右侧抽屉拓宽；展开模式更宽，让观看更好看
const drawerTrack = computed(() => {
  if (artifacts.current) {
    return artifacts.expanded ? "min(1040px, 72vw)" : "clamp(400px, 36vw, 560px)";
  }
  return `${app.drawerWidth}px`;
});

const layoutCols = computed(
  () => `${app.sidebarWidth}px 1fr ${drawerTrack.value}`
);
</script>

<template>
  <div class="shell" :style="{ gridTemplateColumns: layoutCols }">
    <Sidebar />
    <main class="main">
      <SentioBoard v-if="mountedView === 'board'" @open-report="app.openReport" />
      <SentioRadar v-else-if="mountedView === 'radar'" @open-report="app.openReport" />
      <SentioReport v-else-if="mountedView === 'report'" />
      <ChatPanel v-else-if="mountedView === 'chat'" />
      <Automation v-else-if="mountedView === 'automation'" />
      <EnvDoctor v-else-if="mountedView === 'env_doctor'" />
      <UpdatePanel v-else-if="mountedView === 'update'" />
      <Settings v-else-if="mountedView === 'settings'" />
    </main>
    <RightDrawer />

    <!-- 自动更新提示条（发现新版本时浮出） -->
    <UpdateBanner />

    <AddProviderModal v-if="providers.showAddModal" />
    <WorkflowPackModal v-if="workflows.editorOpen" />
    <AutomationModal v-if="automation.editorOpen" />
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
