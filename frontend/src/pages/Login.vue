<script setup lang="ts">
import { onBeforeUnmount, ref } from "vue";
import { API, setToken, suspendAuthRecovery } from "@/api";
import { useAuthGate } from "@/composables/useAuthGate";
import { Loader2Icon } from "lucide-vue-next";
import { Alert, AlertDescription } from "@/components/ui/alert";
import FieldLabel from "@/components/FieldLabel.vue";
import TextInput from "@/ui/TextInput.vue";
import LiveTick from "@/components/chrome/LiveTick.vue";

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

// Mission counter — counts seconds since the page mounted, gives the
// otherwise-static auth screen a heartbeat. Pure decoration.
const elapsed = ref(0);
const handle = window.setInterval(() => (elapsed.value += 1), 1000);
onBeforeUnmount(() => window.clearInterval(handle));
</script>

<template>
  <div class="relative flex h-full items-center justify-center overflow-hidden bg-background dark:bg-starfield">
    <div aria-hidden class="bg-grid pointer-events-none absolute inset-0 opacity-30" />
    <!-- Outer corner ticks — pure ornament, marks the page as an instrument. -->
    <span aria-hidden class="absolute left-6 top-6 text-3xs uppercase tracking-section text-muted-foreground readout">
      ✱ STATION 01 / AUTH
    </span>
    <span aria-hidden class="absolute right-6 top-6 text-3xs uppercase tracking-section text-muted-foreground readout">
      <LiveTick />
    </span>
    <span aria-hidden class="absolute bottom-6 left-6 text-3xs uppercase tracking-section text-muted-foreground readout">
      © {{ year }} · SATHOP MISSION CONSOLE
    </span>
    <span aria-hidden class="absolute bottom-6 right-6 text-3xs uppercase tracking-section text-muted-foreground readout tabular-nums">
      T+{{ String(Math.floor(elapsed / 60)).padStart(2, "0") }}:{{ String(elapsed % 60).padStart(2, "0") }}
    </span>

    <div class="relative grid w-full max-w-[980px] gap-12 px-6 lg:grid-cols-[1.05fr_1fr]">
      <!-- ─── Brand panel — editorial, mission-control vibe. ────────────── -->
      <div class="hidden flex-col justify-between lg:flex">
        <div class="flex items-center gap-3">
          <div class="relative grid h-11 w-11 place-items-center rounded-md border border-border bg-card text-primary shadow-soft">
            <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round">
              <circle cx="12" cy="12" r="6.5" />
              <circle cx="12" cy="12" r="2.4" fill="currentColor" stroke="none" />
              <path d="M12 2v3M12 19v3M2 12h3M19 12h3" />
            </svg>
            <span class="absolute -right-0.5 -top-0.5 h-1.5 w-1.5 rounded-full bg-primary shadow-[0_0_6px_hsl(var(--primary))]" />
          </div>
          <div>
            <div class="font-display text-[22px] font-medium leading-none tracking-tight">SatHop</div>
            <div class="readout mt-1.5 text-3xs uppercase tracking-brand text-muted-foreground">Mission · Console</div>
          </div>
        </div>

        <div class="space-y-7">
          <div class="space-y-3">
            <div class="flex items-center gap-2 text-3xs uppercase tracking-section text-muted-foreground readout">
              <span class="text-primary">§ 00</span>
              <span aria-hidden class="h-px w-12 bg-border" />
              <span>OPERATIONS · BRIEFING</span>
            </div>
            <h1 class="font-display text-balance text-[44px] font-medium leading-[1.04] tracking-tight">
              卫星数据
              <span class="italic text-muted-foreground">·</span>
              <br />
              下载 / 处理 / 分发，
              <br />
              <span class="text-primary">一站调度</span>
            </h1>
          </div>
          <p class="max-w-md text-sm leading-relaxed text-muted-foreground">
            基于 lease 的分布式管线 · SQLite 单事实状态 · 实时事件流 · 用户脚本任务包热插拔。
            HTTP 传输 + 每粒 SHA256 校验，TLS 留给运维层 — 让控制台只关心调度本身。
          </p>
          <div class="flex flex-wrap items-center gap-2">
            <span
              v-for="(t, i) in ['Orchestrator', 'Worker', 'Receiver', 'Bundle Registry']"
              :key="t"
              class="readout inline-flex items-center gap-1.5 rounded-sm border border-border bg-card/80 px-2 py-1 text-3xs uppercase tracking-section text-muted-foreground backdrop-blur"
            >
              <span class="text-primary/70">0{{ i + 1 }}</span>
              <span aria-hidden class="h-2 w-px bg-border" />
              {{ t }}
            </span>
          </div>
        </div>

        <div class="space-y-1.5 text-3xs text-muted-foreground readout uppercase tracking-section">
          <div class="flex items-center gap-2">
            <span class="text-primary">▸</span>
            PULL-BASED · HTTP-ONLY
          </div>
          <div class="flex items-center gap-2">
            <span class="text-primary">▸</span>
            STATE: SQLITE · TRANSPORT: SSE
          </div>
        </div>
      </div>

      <!-- ─── Auth panel — clinical, pin-sharp ──────────────────────────── -->
      <form
        @submit.prevent="submit"
        class="relative overflow-hidden rounded-md border border-border bg-card/95 shadow-pop backdrop-blur"
      >
        <!-- Header strip with section label and live tick -->
        <div class="flex items-center justify-between gap-3 border-b border-border px-6 py-3.5">
          <div class="flex items-center gap-2 text-3xs uppercase tracking-section text-muted-foreground readout">
            <span class="text-primary">§ 01</span>
            <span aria-hidden class="h-2 w-px bg-border" />
            AUTHENTICATE
          </div>
          <span class="signal-led" aria-hidden />
        </div>

        <div class="space-y-6 p-7">
          <div class="space-y-2">
            <div class="font-display text-[26px] font-medium leading-tight tracking-tight">欢迎回来</div>
            <p class="text-sm text-muted-foreground">
              使用 Orchestrator 的
              <code class="rounded bg-muted px-1 py-0.5 readout text-mini text-foreground">SATHOP_TOKEN</code>
              登录。
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
              class="mt-2 readout"
            />
          </label>

          <div v-if="loginError" class="animate-fade-in">
            <Alert variant="destructive"><AlertDescription>{{ loginError }}</AlertDescription></Alert>
          </div>

          <button
            type="submit"
            :disabled="probing || !input.trim()"
            :aria-busy="probing || undefined"
            class="group relative flex w-full items-center justify-center gap-2 overflow-hidden rounded-sm bg-primary px-4 py-2.5 text-sm font-semibold uppercase tracking-section text-primary-foreground shadow-soft transition hover:shadow-glow disabled:cursor-not-allowed disabled:opacity-50"
          >
            <Loader2Icon v-if="probing" class="size-3.5 animate-spin" />
            <span>{{ probing ? "VERIFYING …" : "ENGAGE / 进入控制台" }}</span>
            <span
              v-if="!probing"
              aria-hidden
              class="pointer-events-none absolute inset-0 -translate-x-full bg-gradient-to-r from-transparent via-white/20 to-transparent transition-transform duration-700 group-hover:translate-x-full"
            />
          </button>

          <div class="border-t border-border pt-4 text-3xs leading-relaxed text-muted-foreground readout">
            令牌仅保存在本浏览器 localStorage。
            如需轮换，请在 Orchestrator 容器重新设置
            <span class="text-foreground">SATHOP_TOKEN</span>。
          </div>
        </div>
      </form>
    </div>
  </div>
</template>
