import { defineStore } from "pinia";
import { ref, computed } from "vue";
import {
  convApi,
  type Conversation,
  type Project,
} from "../tauri";

export type ViewKey =
  | "board" // SENTIO 舆情看板
  | "radar" // SENTIO 选股雷达
  | "report" // 个股报告
  | "chat" // 对话后台引擎(无导航，供报告生成调用)
  | "env_doctor"
  | "update"
  | "settings";

export const useAppStore = defineStore("app", () => {
  const view = ref<ViewKey>("board"); // SENTIO 默认进舆情看板
  const sentioStock = ref<string | null>(null); // 当前要看报告的个股代码
  function openReport(code: string) {
    sentioStock.value = code;
    view.value = "report";
  }
  const sidebarCollapsed = ref(false);

  // 置顶对话：仅前端持久化（localStorage），侧栏排序时置顶优先
  const PINNED_KEY = "polaris.pinnedConvs.v1";
  function loadPinned(): Set<string> {
    try {
      const raw = localStorage.getItem(PINNED_KEY);
      if (raw) return new Set(JSON.parse(raw) as string[]);
    } catch {
      /* ignore corrupt storage */
    }
    return new Set();
  }
  const pinnedConvs = ref<Set<string>>(loadPinned());
  function persistPinned() {
    try {
      localStorage.setItem(PINNED_KEY, JSON.stringify([...pinnedConvs.value]));
    } catch {
      /* storage may be unavailable */
    }
  }
  function isPinned(convId: string | null | undefined): boolean {
    return !!convId && pinnedConvs.value.has(convId);
  }
  function togglePin(convId: string) {
    if (!convId) return;
    const s = new Set(pinnedConvs.value);
    if (s.has(convId)) s.delete(convId);
    else s.add(convId);
    pinnedConvs.value = s;
    persistPinned();
  }

  // 任务完成但用户未查看的会话集合 → 侧栏显示墨蓝色未读点
  const unreadConvs = ref<Set<string>>(new Set());
  function markUnread(convId: string) {
    if (!convId) return;
    // 正在查看的对话不标记
    if (convId === currentConvId.value) return;
    unreadConvs.value = new Set(unreadConvs.value).add(convId);
  }
  function clearUnread(convId: string) {
    if (!unreadConvs.value.has(convId)) return;
    const s = new Set(unreadConvs.value);
    s.delete(convId);
    unreadConvs.value = s;
  }

  // 项目 + 对话
  const projects = ref<Project[]>([]);
  const expandedProjects = ref<Set<string>>(new Set());
  const conversationsByProject = ref<Record<string, Conversation[]>>({});
  const currentConvId = ref<string | null>(null);
  const currentProjectId = ref<string | null>(null);

  function setView(v: ViewKey) {
    view.value = v;
  }
  function toggleSidebar() {
    sidebarCollapsed.value = !sidebarCollapsed.value;
  }

  const sidebarWidth = computed(() => (sidebarCollapsed.value ? 48 : 260));

  // MCP 配置弹窗（全局状态，Sidebar 与 App 共用）
  const showMcpModal = ref(false);

  async function refreshProjects() {
    projects.value = await convApi.listProjects();
    if (!currentProjectId.value && projects.value.length) {
      currentProjectId.value = projects.value[0].id;
      expandedProjects.value.add(currentProjectId.value);
      await refreshConversations(currentProjectId.value);
    }
  }

  async function refreshConversations(projectId: string) {
    conversationsByProject.value[projectId] =
      await convApi.listConversations(projectId);
    // Vue 3 reactive: 替换 ref 触发更新
    conversationsByProject.value = { ...conversationsByProject.value };
  }

  async function toggleProject(projectId: string) {
    if (expandedProjects.value.has(projectId)) {
      expandedProjects.value.delete(projectId);
    } else {
      expandedProjects.value.add(projectId);
      if (!conversationsByProject.value[projectId]) {
        await refreshConversations(projectId);
      }
    }
    expandedProjects.value = new Set(expandedProjects.value);
  }

  async function createProject(name: string) {
    const p = await convApi.createProject(name);
    projects.value = [...projects.value, p];
    expandedProjects.value = new Set([...expandedProjects.value, p.id]);
    currentProjectId.value = p.id;
    conversationsByProject.value = { ...conversationsByProject.value, [p.id]: [] };
    return p;
  }

  // 归档项目 = 从活动列表移除(后端只置 archived 标记, 对话/消息保留, 不做硬删除)
  async function archiveProject(projectId: string) {
    await convApi.archiveProject(projectId);
    projects.value = projects.value.filter((p) => p.id !== projectId);
    const next = { ...conversationsByProject.value };
    delete next[projectId];
    conversationsByProject.value = next;
    if (expandedProjects.value.has(projectId)) {
      expandedProjects.value.delete(projectId);
      expandedProjects.value = new Set(expandedProjects.value);
    }
    // 当前项目被归档 → 回退到第一个剩余项目
    if (currentProjectId.value === projectId) {
      currentProjectId.value = projects.value[0]?.id ?? null;
    }
  }

  // 在系统文件管理器中打开该项目的工作目录
  async function openProjectDir(projectId: string) {
    await convApi.openProjectDir(projectId);
  }

  /**
   * @param navigate 是否切到 chat 视图。默认 true(侧栏/对话面板新建即跳进对话)。
   *   工坊类组件(Deck/Web 等)自己管理视图、就地展示预览, 必须传 false ——
   *   否则 setView('chat') 会卸载工坊组件、连带销毁其状态机/预览/「继续修改」。
   */
  async function createConversation(projectId: string, navigate = true) {
    const c = await convApi.createConversation(projectId);
    const cur = conversationsByProject.value[projectId] ?? [];
    conversationsByProject.value = {
      ...conversationsByProject.value,
      [projectId]: [c, ...cur],
    };
    expandedProjects.value = new Set([...expandedProjects.value, projectId]);
    currentConvId.value = c.id;
    currentProjectId.value = projectId;
    if (navigate) setView("chat");
    return c;
  }

  async function deleteConversation(conv: Conversation) {
    await convApi.deleteConversation(conv.id);
    const cur = conversationsByProject.value[conv.projectId] ?? [];
    conversationsByProject.value = {
      ...conversationsByProject.value,
      [conv.projectId]: cur.filter((c) => c.id !== conv.id),
    };
    if (currentConvId.value === conv.id) {
      currentConvId.value = null;
    }
    // 删除后顺手清掉置顶标记，避免遗留垃圾
    if (pinnedConvs.value.has(conv.id)) togglePin(conv.id);
  }

  async function renameConversation(conv: Conversation, title: string) {
    const t = title.trim();
    if (!t || t === conv.title) return;
    await convApi.renameConversation(conv.id, t);
    const cur = conversationsByProject.value[conv.projectId] ?? [];
    conversationsByProject.value = {
      ...conversationsByProject.value,
      [conv.projectId]: cur.map((c) => (c.id === conv.id ? { ...c, title: t } : c)),
    };
  }

  function selectConversation(conv: Conversation) {
    currentConvId.value = conv.id;
    currentProjectId.value = conv.projectId;
    clearUnread(conv.id);
    setView("chat");
  }

  return {
    // ui
    view,
    sentioStock,
    openReport,
    sidebarCollapsed,
    sidebarWidth,
    showMcpModal,
    setView,
    toggleSidebar,
    unreadConvs,
    markUnread,
    clearUnread,
    // pin
    pinnedConvs,
    isPinned,
    togglePin,
    // conv
    projects,
    expandedProjects,
    conversationsByProject,
    currentConvId,
    currentProjectId,
    refreshProjects,
    refreshConversations,
    toggleProject,
    createProject,
    archiveProject,
    openProjectDir,
    createConversation,
    deleteConversation,
    renameConversation,
    selectConversation,
  };
});
