<script setup lang="ts">
// 全局自动更新提示：启动检测到新版本时，无论当前在哪个页面都会自动弹出。
// 数据全部来自 useUpdater 的后端状态机派生量；「以后再说」只关本次会话弹窗（更新 tab 入口仍在）。
import { computed } from "vue";
import { Sparkles, Rocket, LoaderCircle, X } from "@lucide/vue";
import {
  updateVersion, updateNotes, updating, updateProgress,
  dialogDismissed, applyUpdate, dismissUpdate,
} from "../composables/useUpdater";

// 有新版本 && 未被「以后再说」关掉 → 自动显形
const show = computed(() => !!updateVersion.value && !dialogDismissed.value);
</script>

<template>
  <transition name="ub">
    <div v-if="show" class="ub-card" role="alertdialog" aria-label="发现新版本">
      <button class="ub-x" title="以后再说" @click="dismissUpdate"><X :size="15" :stroke-width="2" /></button>
      <div class="ub-top">
        <span class="ub-badge"><Sparkles :size="18" :stroke-width="1.7" /></span>
        <div class="ub-meta">
          <div class="ub-title">发现新版本 <b>v{{ updateVersion }}</b></div>
          <div class="ub-hint">
            {{ updating ? "正在下载，完成后自动重启生效" : "点「立即更新」后台下载安装，自动重启即用" }}
          </div>
        </div>
      </div>

      <div v-if="updateNotes && !updating" class="ub-notes">{{ updateNotes }}</div>

      <div v-if="updating" class="ub-bar"><div class="ub-fill" :style="{ width: updateProgress + '%' }"></div></div>

      <div class="ub-btns">
        <button v-if="!updating" class="ub-later" @click="dismissUpdate">以后再说</button>
        <button class="ub-go" :disabled="updating" @click="applyUpdate">
          <LoaderCircle v-if="updating" :size="14" :stroke-width="2" class="ub-spin" />
          <Rocket v-else :size="14" :stroke-width="1.9" />
          <span>{{ updating ? `更新中 ${updateProgress}%` : "立即更新" }}</span>
        </button>
      </div>
    </div>
  </transition>
</template>

<style scoped>
.ub-card {
  position: fixed;
  right: 22px;
  bottom: 22px;
  z-index: 9000;
  width: 340px;
  padding: 16px 16px 14px;
  background: var(--panel, #121826);
  border: 1px solid color-mix(in srgb, var(--primary, #5b8cff) 32%, transparent);
  border-radius: 16px;
  box-shadow: 0 18px 50px rgba(0, 0, 0, 0.4), 0 0 0 1px rgba(255, 255, 255, 0.03);
  color: var(--text, #f0f3fa);
  font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Microsoft YaHei", sans-serif;
}
.ub-x {
  position: absolute; top: 10px; right: 10px;
  width: 24px; height: 24px; border: none; background: transparent;
  color: var(--muted, #8a93a8); border-radius: 6px; display: inline-flex;
  align-items: center; justify-content: center; cursor: pointer;
}
.ub-x:hover { background: rgba(255, 255, 255, 0.08); color: var(--text, #f0f3fa); }
.ub-top { display: flex; gap: 12px; align-items: flex-start; padding-right: 22px; }
.ub-badge {
  width: 34px; height: 34px; border-radius: 9px; flex-shrink: 0;
  background: var(--primary-soft, rgba(91, 140, 255, 0.16)); color: var(--primary, #5b8cff);
  display: inline-flex; align-items: center; justify-content: center;
}
.ub-title { font-size: 14px; font-weight: 600; }
.ub-title b { color: var(--primary, #5b8cff); }
.ub-hint { margin-top: 3px; font-size: 11.5px; color: var(--muted, #8a93a8); line-height: 1.5; }
.ub-notes {
  margin-top: 12px; max-height: 96px; overflow-y: auto; padding: 9px 11px;
  background: rgba(255, 255, 255, 0.04); border-radius: 9px;
  font-size: 11.5px; line-height: 1.6; color: var(--text-2, #c4cad6); white-space: pre-wrap;
}
.ub-bar { margin-top: 13px; height: 6px; border-radius: 3px; background: rgba(255, 255, 255, 0.08); overflow: hidden; }
.ub-fill { height: 100%; background: var(--primary, #5b8cff); border-radius: 3px; transition: width 0.2s ease; }
.ub-btns { display: flex; gap: 9px; margin-top: 14px; }
.ub-later {
  flex-shrink: 0; padding: 9px 14px; border: 1px solid var(--border, rgba(255, 255, 255, 0.12));
  border-radius: 10px; background: transparent; color: var(--muted, #8a93a8); font-size: 12.5px; cursor: pointer;
}
.ub-later:hover { color: var(--text, #f0f3fa); border-color: var(--muted, #8a93a8); }
.ub-go {
  flex: 1; padding: 9px 0; border: none; border-radius: 10px;
  background: linear-gradient(120deg, #5b8cff, #00e0c6); color: #04121a;
  font-size: 13px; font-weight: 700; display: inline-flex; align-items: center; justify-content: center; gap: 7px; cursor: pointer;
}
.ub-go:disabled { opacity: 0.85; cursor: default; }
.ub-spin { animation: ub-spin 0.9s linear infinite; }
@keyframes ub-spin { to { transform: rotate(360deg); } }

.ub-enter-active, .ub-leave-active { transition: opacity 0.25s ease, transform 0.25s ease; }
.ub-enter-from, .ub-leave-to { opacity: 0; transform: translateY(14px); }
</style>
