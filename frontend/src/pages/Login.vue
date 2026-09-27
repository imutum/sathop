<script setup lang="ts">
import { ref } from "vue";
import { API, setToken, suspendAuthRecovery } from "@/api";
import { useAuthGate } from "@/composables/useAuthGate";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import FieldLabel from "@/components/FieldLabel.vue";
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
        ? "访问令牌无效，请核对后重试。"
        : `无法连接调度服务：${msg}`;
  } finally {
    probing.value = false;
  }
}

const year = new Date().getFullYear();
</script>

<template>
  <div class="relative flex h-full items-center justify-center overflow-hidden bg-background">
    <div aria-hidden class="bg-dotgrid pointer-events-none absolute inset-0 opacity-35" />

    <div class="relative grid w-full max-w-[920px] gap-10 px-6 lg:grid-cols-[1.1fr_1fr]">
      <!-- ─── Brand panel (md+ only) ────────────────────────────────────── -->
      <div class="hidden flex-col justify-between lg:flex">
        <div class="flex items-center gap-3">
          <div class="grid h-11 w-11 place-items-center rounded-lg border border-border bg-background text-foreground shadow-soft">
            <svg aria-hidden="true" viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
              <path d="M21 12.79A9 9 0 1 1 11.21 3" />
              <circle cx="12" cy="12" r="2.4" fill="currentColor" stroke="none" />
            </svg>
          </div>
          <div>
            <div class="text-lg font-semibold">SatHop</div>
            <div class="text-2xs uppercase tracking-brand text-muted-foreground">数据服务控制台</div>
          </div>
        </div>

        <div class="space-y-6">
          <h1 class="text-balance text-3xl font-semibold leading-tight">
            遥感数据
            <br />
            <span class="text-primary">下载 · 处理 · 交付</span>
          </h1>
          <p class="max-w-sm text-sm leading-relaxed text-muted-foreground">
            集中管理数据任务，跟踪处理进度，核对交付结果。
          </p>
        </div>

        <div class="text-2xs text-muted-foreground">
          © {{ year }} SatHop
        </div>
      </div>

      <!-- ─── Login card ────────────────────────────────────────────────── -->
      <form
        @submit.prevent="submit"
        class="rounded-lg border border-border bg-background/95 p-8 shadow-pop backdrop-blur"
      >
        <div class="mb-6">
          <div class="text-xl font-semibold">登录控制台</div>
          <p class="mt-1.5 text-xs text-muted-foreground">
            输入部署时设置的访问令牌。
          </p>
        </div>

        <label class="block">
          <FieldLabel required>访问令牌</FieldLabel>
          <TextInput
            autofocus
            type="password"
            autocomplete="current-password"
            aria-label="访问令牌"
            v-model="input"
            @input="loginError = null"
            placeholder="输入访问令牌"
            class="mt-2 font-mono"
          />
        </label>

        <div v-if="loginError" class="mt-3 animate-fade-in">
          <Alert variant="destructive"><AlertDescription>{{ loginError }}</AlertDescription></Alert>
        </div>

        <Button
          type="submit"
          size="lg"
          class="mt-5 w-full"
          :disabled="!input.trim()"
          :pending="probing"
          pending-label="验证中…"
        >
          进入控制台
        </Button>

        <div class="mt-6 border-t border-border pt-4 text-2xs leading-relaxed text-muted-foreground">
          登录后，令牌将保存在当前浏览器。如需更换，请更新调度服务的
          <span class="font-mono text-foreground">SATHOP_TOKEN</span>。
        </div>
      </form>
    </div>
  </div>
</template>
