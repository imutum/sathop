<script setup lang="ts">
import { ref } from "vue";
import { API, setToken, suspendAuthRecovery } from "@/api";
import { useAuthGate } from "@/composables/useAuthGate";
import Alert from "@/ui/Alert.vue";
import FieldLabel from "@/ui/FieldLabel.vue";
import Spinner from "@/ui/Spinner.vue";
import TextInput from "@/ui/TextInput.vue";

const { markReady } = useAuthGate();

const input = ref("");
const probing = ref(false);
const loginError = ref<string | null>(null);

async function submit() {
  const t = input.value.trim();
  if (!t) return;
  probing.value = true;
  loginError.value = null;
  const prev = localStorage.getItem("sathop.token");
  setToken(t);
  try {
    await suspendAuthRecovery(() => API.orchestratorInfo());
    markReady();
  } catch (e) {
    const msg = (e as Error).message;
    if (prev) setToken(prev);
    else localStorage.removeItem("sathop.token");
    loginError.value =
      msg.startsWith("401") || msg.startsWith("403")
        ? "令牌被 Orchestrator 拒绝，请检查 SATHOP_TOKEN。"
        : `无法连接 Orchestrator：${msg}`;
  } finally {
    probing.value = false;
  }
}

const year = new Date().getFullYear();
</script>

<template>
  <div class="relative flex h-full items-center justify-center overflow-hidden bg-legacy-bg">
    <div aria-hidden class="bg-dotgrid pointer-events-none absolute inset-0 opacity-35" />

    <div class="relative grid w-full max-w-[920px] gap-10 px-6 lg:grid-cols-[1.1fr_1fr]">
      <!-- Brand panel -->
      <div class="hidden flex-col justify-between lg:flex">
        <div class="flex items-center gap-3">
          <div class="grid h-11 w-11 place-items-center rounded-lg border border-border bg-legacy-surface text-legacy-text shadow-soft">
            <svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
              <path d="M21 12.79A9 9 0 1 1 11.21 3" />
              <circle cx="12" cy="12" r="2.4" fill="currentColor" stroke="none" />
            </svg>
          </div>
          <div>
            <div class="font-display text-lg font-semibold">SatHop</div>
            <div class="text-[11px] uppercase tracking-[0.18em] text-legacy-muted">Mission Console</div>
          </div>
        </div>

        <div class="space-y-6">
          <h1 class="font-display text-balance text-3xl font-semibold leading-tight">
            卫星数据
            <br />
            下载 · 处理 · 分发
            <br />
            <span class="text-legacy-accent">一站调度</span>
          </h1>
          <p class="max-w-sm text-sm leading-relaxed text-legacy-muted">
            基于 lease 的分布式管线 · SQLite 单事实状态 · 实时事件流 · 用户脚本任务包热插拔。
          </p>
          <div class="flex flex-wrap items-center gap-2 text-[11px] text-legacy-muted">
            <span v-for="t in ['Orchestrator', 'Worker', 'Receiver', 'Bundle Registry']" :key="t"
                  class="rounded-full border border-border bg-legacy-surface/80 px-2.5 py-1 font-mono text-[10.5px] text-legacy-muted backdrop-blur">
              {{ t }}
            </span>
          </div>
        </div>

        <div class="text-[11px] text-legacy-muted">
          © {{ year }} SatHop · Pull-based · HTTP-only
        </div>
      </div>

      <!-- Login card -->
      <form
        @submit.prevent="submit"
        class="rounded-lg border border-border bg-legacy-surface/95 p-8 shadow-pop backdrop-blur"
      >
        <div class="mb-6">
          <div class="font-display text-xl font-semibold">欢迎回来</div>
          <p class="mt-1.5 text-xs text-legacy-muted">
            使用 Orchestrator 的 <code class="rounded bg-legacy-subtle px-1 py-0.5 font-mono text-[10.5px]">SATHOP_TOKEN</code> 登录。
          </p>
        </div>

        <label class="block">
          <FieldLabel required>API 令牌</FieldLabel>
          <TextInput
            autofocus
            type="password"
            autocomplete="current-password"
            aria-label="Orchestrator API 令牌"
            v-model="input"
            @input="loginError = null"
            placeholder="sk_… 或部署时设置的 token"
            class="mt-2 font-mono"
          />
        </label>

        <div v-if="loginError" class="mt-3 animate-fade-in">
          <Alert>{{ loginError }}</Alert>
        </div>

        <button
          type="submit"
          :disabled="probing || !input.trim()"
          :aria-busy="probing || undefined"
          class="mt-5 flex w-full items-center justify-center gap-2 rounded-md bg-legacy-accent px-3 py-2.5 text-sm font-semibold text-legacy-accent-fg shadow-soft transition hover:bg-legacy-accent/90 disabled:cursor-not-allowed disabled:opacity-50"
        >
          <Spinner v-if="probing" />
          {{ probing ? "验证中…" : "进入控制台" }}
        </button>

        <div class="mt-6 border-t border-border pt-4 text-[11px] leading-relaxed text-legacy-muted">
          令牌仅保存在本浏览器 localStorage。
          如需轮换，请在 Orchestrator 容器重新设置 <span class="font-mono text-legacy-text">SATHOP_TOKEN</span>。
        </div>
      </form>
    </div>
  </div>
</template>
