<script setup lang="ts">
import { ref } from "vue";
import { API, setToken, suspendAuthRecovery } from "@/api";
import { useAuthGate } from "@/composables/useAuthGate";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import FieldLabel from "@/components/FieldLabel.vue";
import TextInput from "@/ui/TextInput.vue";
import BrandMark from "@/components/BrandMark.vue";

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
  <div class="relative min-h-full overflow-x-hidden bg-background px-5 py-8 sm:px-10 lg:flex lg:items-center lg:py-16">
    <div class="relative mx-auto grid w-full max-w-[1080px] items-center gap-10 lg:grid-cols-[1.2fr_1fr] lg:gap-20">
      <div class="relative">
        <div class="flex items-center gap-3">
          <BrandMark class="size-11" />
          <div>
            <div class="text-xl font-semibold tracking-tight">SatHop</div>
            <div class="mt-1 text-xs text-muted-foreground">数据服务控制台</div>
          </div>
        </div>

        <div class="relative mt-16 hidden lg:block">
          <div class="mb-5 flex items-center gap-3 text-xs font-medium tracking-label text-primary">
            <span class="h-px w-8 bg-primary/50" /> 遥感数据工作空间
          </div>
          <h1 class="text-[46px] font-semibold leading-[1.3] tracking-tight">
            遥感数据，<br /><span class="text-primary">从处理到交付。</span>
          </h1>
          <p class="mt-6 max-w-sm text-sm leading-7 text-muted-foreground">
            集中管理数据任务，跟踪处理进度，核对交付结果。
          </p>
          <svg aria-hidden="true" viewBox="0 0 460 140" class="mt-10 w-full max-w-[440px] text-primary" fill="none">
            <path d="M20 90C120 90 140 30 235 30S350 90 440 90" stroke="currentColor" stroke-opacity=".18" />
            <path d="M20 90H440" stroke="currentColor" stroke-opacity=".15" stroke-dasharray="3 7" />
            <ellipse cx="235" cy="70" rx="85" ry="55" stroke="currentColor" stroke-opacity=".18" />
            <ellipse cx="235" cy="70" rx="45" ry="55" stroke="currentColor" stroke-opacity=".12" />
            <circle cx="40" cy="90" r="5" fill="currentColor" fill-opacity=".65" />
            <circle cx="235" cy="30" r="5" fill="currentColor" />
            <circle cx="420" cy="90" r="5" fill="currentColor" fill-opacity=".65" />
          </svg>
          <div class="flex justify-between pr-5 text-xs text-muted-foreground"><span>01 / 下载</span><span>02 / 处理</span><span>03 / 交付</span></div>
        </div>
      </div>

      <form
        @submit.prevent="submit"
        class="w-full rounded-2xl border border-border bg-card p-7 shadow-pop sm:p-9"
      >
        <div class="mb-8">
          <h2 class="text-2xl font-semibold tracking-tight">登录控制台</h2>
          <p class="mt-2 text-sm text-muted-foreground">
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
            class="mt-2 h-11 font-mono"
          />
        </label>

        <div v-if="loginError" class="mt-3 animate-fade-in">
          <Alert variant="destructive"><AlertDescription>{{ loginError }}</AlertDescription></Alert>
        </div>

        <Button
          type="submit"
          size="lg"
          class="mt-6 w-full"
          :disabled="!input.trim()"
          :pending="probing"
          pending-label="验证中…"
        >
          进入控制台
        </Button>

        <div class="mt-8 border-t border-border pt-5 text-xs leading-6 text-muted-foreground">
          登录后，令牌将保存在当前浏览器。如需更换，请更新调度服务的
          <span class="font-mono text-foreground">SATHOP_TOKEN</span>。
        </div>
      </form>
      <div class="text-xs text-muted-foreground lg:col-span-2">© {{ year }} SatHop</div>
    </div>
  </div>
</template>
