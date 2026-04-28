<script setup lang="ts">
import { ref } from "vue";
import { API, setToken, suspendAuthRecovery } from "./api";
import { useAuthGate } from "./composables/useAuthGate";
import Alert from "./ui/Alert.vue";
import FieldLabel from "./ui/FieldLabel.vue";
import Spinner from "./ui/Spinner.vue";

const { markReady } = useAuthGate();

const input = ref("");
const probing = ref(false);
const err = ref<string | null>(null);

async function submit() {
  const t = input.value.trim();
  if (!t) return;
  probing.value = true;
  err.value = null;
  const prev = localStorage.getItem("sathop.token");
  setToken(t);
  try {
    await suspendAuthRecovery(() => API.orchestratorInfo());
    markReady();
  } catch (e) {
    const msg = (e as Error).message;
    if (prev) setToken(prev);
    else localStorage.removeItem("sathop.token");
    err.value =
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
  <div class="relative flex h-full items-center justify-center overflow-hidden bg-bg">
    <div aria-hidden class="bg-radial-fade pointer-events-none absolute inset-0" />
    <div aria-hidden class="bg-dotgrid pointer-events-none absolute inset-0 opacity-40" />

    <div class="relative grid w-full max-w-[920px] gap-10 px-6 lg:grid-cols-[1.1fr_1fr]">
      <!-- Brand panel -->
      <div class="hidden flex-col justify-between lg:flex">
        <div class="flex items-center gap-3">
          <div class="grid h-11 w-11 place-items-center rounded-2xl bg-gradient-to-br from-accent to-accent/60 text-accent-fg shadow-glow">
            <svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
              <path d="M21 12.79A9 9 0 1 1 11.21 3" />
              <circle cx="12" cy="12" r="2.4" fill="currentColor" stroke="none" />
            </svg>
          </div>
          <div>
            <div class="font-display text-lg font-semibold tracking-tight">SatHop</div>
            <div class="text-[11px] uppercase tracking-[0.18em] text-muted">Mission Console</div>
          </div>
        </div>

        <div class="space-y-6">
          <h1 class="font-display text-balance text-3xl font-semibold leading-tight tracking-tight">
            卫星数据
            <br />
            下载 · 处理 · 分发
            <br />
            <span class="text-accent">一站调度</span>
          </h1>
          <p class="max-w-sm text-sm leading-relaxed text-muted">
            基于 lease 的分布式管线 · SQLite 单事实状态 · 实时事件流 · 用户脚本任务包热插拔。
          </p>
          <div class="flex flex-wrap items-center gap-2 text-[11px] text-muted">
            <span v-for="t in ['Orchestrator', 'Worker', 'Receiver', 'Bundle Registry']" :key="t"
                  class="rounded-full border border-border bg-surface/80 px-2.5 py-1 font-mono text-[10.5px] text-muted backdrop-blur">
              {{ t }}
            </span>
          </div>
        </div>

        <div class="text-[11px] text-muted">
          © {{ year }} SatHop · Pull-based · HTTP-only
        </div>
      </div>

      <!-- Login card -->
      <form
        @submit.prevent="submit"
        class="rounded-2xl border border-border bg-surface/80 p-8 shadow-pop backdrop-blur-xl"
      >
        <div class="mb-6">
          <div class="font-display text-xl font-semibold tracking-tight">欢迎回来</div>
          <p class="mt-1.5 text-xs text-muted">
            使用 Orchestrator 的 <code class="rounded bg-subtle px-1 py-0.5 font-mono text-[10.5px]">SATHOP_TOKEN</code> 登录。
          </p>
        </div>

        <label class="block">
          <FieldLabel required>API 令牌</FieldLabel>
          <input
            autofocus
            type="password"
            autocomplete="current-password"
            aria-label="Orchestrator API 令牌"
            v-model="input"
            @input="err = null"
            placeholder="sk_… 或部署时设置的 token"
            class="input mt-2 py-2.5 font-mono text-sm text-text placeholder:text-muted/60"
          />
        </label>

        <div v-if="err" class="mt-3 animate-fade-in">
          <Alert>{{ err }}</Alert>
        </div>

        <button
          type="submit"
          :disabled="probing || !input.trim()"
          :aria-busy="probing || undefined"
          class="mt-5 flex w-full items-center justify-center gap-2 rounded-lg bg-accent px-3 py-2.5 text-sm font-semibold text-accent-fg shadow-glow transition hover:bg-accent/90 disabled:cursor-not-allowed disabled:opacity-50"
        >
          <Spinner v-if="probing" />
          {{ probing ? "验证中…" : "进入控制台" }}
        </button>

        <div class="mt-6 border-t border-border pt-4 text-[11px] leading-relaxed text-muted">
          令牌仅保存在本浏览器 localStorage。
          如需轮换，请在 Orchestrator 容器重新设置 <span class="font-mono text-text">SATHOP_TOKEN</span>。
        </div>
      </form>
    </div>
  </div>
</template>
