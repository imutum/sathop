<script setup lang="ts">
import { computed, ref } from "vue";
import { useQuery } from "@tanstack/vue-query";
import { RouterLink } from "vue-router";
import { API } from "@/api";
import { K } from "@/queryKeys";
import { getToken } from "@/apiClient";
import { useToast } from "@/composables/useToast";
import { Icon } from "@/components/Icon";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import Modal from "@/ui/Modal.vue";
import {
  DEFAULT_RECEIVER_DIR,
  type TlsMode,
  hostDirPrestep,
  isAbsolutePath,
  receiverDockerCompose,
  receiverDockerRun,
  receiverOpsHint,
  receiverUvx,
} from "@/features/onboarding/snippets";
import { useRegistrationWatch } from "@/features/onboarding/useRegistrationWatch";

defineEmits<{ close: [] }>();

const toast = useToast();

const receiverId = ref(`recv-${Math.random().toString(36).slice(2, 8)}`);
const token = ref(getToken());
const orchUrl = ref(window.location.origin);
const outputDir = ref(DEFAULT_RECEIVER_DIR);
const concurrent = ref(4);
const poll = ref(10);
// Default matches the worker modal's default expose mode (selfsigned). The
// three options below are ordered to mirror the three deployment postures:
// trust-orch (selfsigned worker), strict (Caddy/public CA worker), insecure.
const tlsMode = ref<TlsMode>("trust-orch");
const showToken = ref(false);

type TabKey = "docker-run" | "compose" | "uvx";
const activeTab = ref<TabKey>("docker-run");
const tabs: Array<{ key: TabKey; label: string; hint: string }> = [
  { key: "docker-run", label: "Docker Run", hint: "一行命令，最直接" },
  { key: "compose", label: "Docker Compose", hint: "保存为 docker-compose.yml 后 docker compose up -d" },
  { key: "uvx", label: "Python (uvx)", hint: "无需 docker，需要本机已装 uv" },
];

const cfg = computed(() => ({
  receiverId: receiverId.value.trim() || "recv-unnamed",
  token: token.value,
  orchUrl: orchUrl.value.trim().replace(/\/api\/?$/, ""),
  outputDir: outputDir.value.trim() || DEFAULT_RECEIVER_DIR,
  concurrent: concurrent.value,
  poll: poll.value,
  tlsMode: tlsMode.value,
}));

// Relative paths pin the mount target to docker's invocation PWD — copy the
// command into a different directory and you write to a different archive.
// Allow it (still useful for ad-hoc tests) but surface a warning.
const outputDirRelative = computed(() => !isAbsolutePath(cfg.value.outputDir));

const snippet = computed(() => {
  switch (activeTab.value) {
    case "docker-run":
      return `${receiverDockerRun(cfg.value)}\n\n${receiverOpsHint()}`;
    case "compose":
      return receiverDockerCompose(cfg.value);
    case "uvx":
      return receiverUvx(cfg.value);
  }
  return "";
});

const valid = computed(
  () =>
    cfg.value.receiverId.length > 0 &&
    cfg.value.token.length > 0 &&
    cfg.value.orchUrl.length > 0 &&
    cfg.value.outputDir.length > 0,
);

// After-copy registration watcher. Shares the global TanStack Query cache,
// so SSE-driven invalidation (useLiveStream) refetches automatically when
// the orchestrator publishes a `receivers` scope nudge — no extra polling.
const receiversQuery = useQuery({ queryKey: [...K.receivers], queryFn: API.receivers });
const registrationWatch = useRegistrationWatch(
  computed(() => cfg.value.receiverId),
  receiversQuery.data,
  (r, id) => r.receiver_id === id,
);

async function copySnippet() {
  await navigator.clipboard.writeText(snippet.value);
  toast.success("已复制到剪贴板");
  registrationWatch.start();
}
</script>

<template>
  <Modal width-class="w-[min(820px,95vw)]" @close="$emit('close')">
    <h2 class="mb-1 text-lg font-semibold">接入新接收端</h2>
    <p class="mb-5 text-xs text-muted-foreground">
      填好下面的参数 → 复制下方一段命令到目标机器执行 → 接收端会自动注册并开始拉取产物
    </p>

    <div class="grid grid-cols-1 gap-3 text-sm md:grid-cols-2">
      <div>
        <Label for="ob-id">Receiver ID</Label>
        <Input id="ob-id" v-model="receiverId" placeholder="recv-xxx" class="font-mono text-xs" />
      </div>
      <div>
        <Label for="ob-dir">归档目录（host 绝对路径）</Label>
        <Input
          id="ob-dir"
          v-model="outputDir"
          :placeholder="DEFAULT_RECEIVER_DIR"
          class="font-mono text-xs"
        />
      </div>
      <div class="md:col-span-2">
        <Label for="ob-orch">Orchestrator URL</Label>
        <Input
          id="ob-orch"
          v-model="orchUrl"
          placeholder="http://orch.example.com:8765"
          class="font-mono text-xs"
        />
      </div>
      <div class="md:col-span-2">
        <Label for="ob-token">Token</Label>
        <div class="relative">
          <Input
            id="ob-token"
            v-model="token"
            :type="showToken ? 'text' : 'password'"
            placeholder="orchestrator bearer token"
            class="pr-9 font-mono text-xs"
          />
          <Button
            type="button"
            variant="ghost"
            size="icon-sm"
            class="absolute right-1 top-1/2 h-7 w-7 -translate-y-1/2 text-muted-foreground"
            :title="showToken ? '隐藏' : '显示'"
            @click="showToken = !showToken"
          >
            <Icon :name="showToken ? 'x' : 'info'" :size="13" />
          </Button>
        </div>
        <p class="mt-1 text-2xs text-muted-foreground">
          默认填的是当前登录 token；要发给同事，可以换成另一个有权限的 token
        </p>
      </div>
    </div>

    <Alert v-if="outputDirRelative" variant="destructive" class="mt-3">
      <AlertDescription class="text-2xs">
        相对路径会被锚定到 <code class="font-mono">docker run</code> 的当前目录——换个目录复制粘贴就会写到别处。建议使用绝对路径（例如 <code class="font-mono">{{ DEFAULT_RECEIVER_DIR }}</code>）
      </AlertDescription>
    </Alert>

    <p class="mt-2 text-2xs text-muted-foreground">
      命令统一假设 bash 兼容 shell（Linux / macOS / WSL / Git Bash）。Windows 用户请在 WSL 或 Git Bash 中执行——<code class="font-mono">$(id -u)</code>、<code class="font-mono">$(pwd)</code>、<code class="font-mono">\</code> 续行均为 bash 语法
    </p>

    <div class="mt-3">
      <Label>TLS 信任模式</Label>
      <div class="mt-1 grid grid-cols-1 gap-1 rounded-md border border-border bg-muted/40 p-0.5 md:grid-cols-3">
        <button
          type="button"
          class="rounded px-3 py-1.5 text-xs font-medium transition-colors"
          :class="tlsMode === 'trust-orch' ? 'bg-background text-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground'"
          @click="tlsMode = 'trust-orch'"
        >
          信任调度中心 CA（自签 worker，推荐）
        </button>
        <button
          type="button"
          class="rounded px-3 py-1.5 text-xs font-medium transition-colors"
          :class="tlsMode === 'strict' ? 'bg-background text-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground'"
          @click="tlsMode = 'strict'"
        >
          仅公网 CA（Caddy 域名 worker）
        </button>
        <button
          type="button"
          class="rounded px-3 py-1.5 text-xs font-medium transition-colors"
          :class="tlsMode === 'insecure' ? 'bg-background text-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground'"
          @click="tlsMode = 'insecure'"
        >
          跳过验证（不安全）
        </button>
      </div>
      <p class="mt-1.5 text-2xs text-muted-foreground">
        <span v-if="tlsMode === 'trust-orch'">
          启动时从调度中心拉取所有 worker 的 CA 形成可信清单。中间人没有 worker 私钥就过不了 TLS — 内网最佳搭配
        </span>
        <span v-else-if="tlsMode === 'strict'">
          只信任系统 CA（Let's Encrypt 等公开证书）。Worker 用「自签 IP + HTTPS」时会握手失败 — 仅公网域名 worker 适用
        </span>
        <span v-else>
          完全跳过证书验证，加密但不验身份。Worker 走明文 HTTP 时 TLS 模式本就无效；仅在严格管控的物理网络下使用
        </span>
      </p>
    </div>

    <details class="mt-3 rounded-lg border border-border bg-muted/40 px-3 py-2.5">
      <summary class="cursor-pointer text-xs font-medium text-muted-foreground transition-colors hover:text-foreground">
        高级：并发数 / 心跳间隔
      </summary>
      <div class="mt-2 grid grid-cols-2 gap-3">
        <div>
          <Label for="ob-conc">并发拉取</Label>
          <Input id="ob-conc" v-model.number="concurrent" type="number" min="1" max="32" />
        </div>
        <div>
          <Label for="ob-poll">心跳/拉取间隔（秒）</Label>
          <Input id="ob-poll" v-model.number="poll" type="number" min="1" max="120" />
        </div>
      </div>
    </details>

    <Alert v-if="!valid" variant="destructive" class="mt-4">
      <AlertDescription>
        Receiver ID / Token / Orchestrator URL / 输出目录 都不能为空
      </AlertDescription>
    </Alert>

    <div class="mt-5">
      <Tabs v-model="activeTab" class="flex flex-wrap items-end justify-between gap-3">
        <TabsList>
          <TabsTrigger v-for="t in tabs" :key="t.key" :value="t.key">
            {{ t.label }}
          </TabsTrigger>
        </TabsList>
        <span class="text-2xs text-muted-foreground">
          {{ tabs.find((t) => t.key === activeTab)?.hint }}
        </span>
      </Tabs>

      <div v-if="activeTab === 'docker-run'" class="mt-3">
        <Alert>
          <AlertDescription class="space-y-1.5">
            <div class="text-xs">先在目标机器上确保宿主目录存在并归当前用户：</div>
            <pre class="overflow-x-auto rounded bg-muted px-2 py-1.5 font-mono text-2xs">{{ hostDirPrestep(cfg.outputDir) }}</pre>
          </AlertDescription>
        </Alert>
      </div>

      <div class="relative mt-3 rounded-lg border border-border bg-muted/40">
        <div class="absolute right-2 top-2">
          <Button
            type="button"
            size="sm"
            variant="outline"
            :disabled="!valid"
            class="h-7 gap-1.5 px-2 text-2xs"
            @click="copySnippet"
          >
            <Icon name="clipboard" :size="11" />
            复制
          </Button>
        </div>
        <pre class="overflow-x-auto p-3 pr-20 font-mono text-2xs leading-relaxed">{{ snippet }}</pre>
      </div>

      <p v-if="activeTab === 'uvx'" class="mt-2 text-2xs text-muted-foreground">
        前提：目标机器已安装 uv（<code class="font-mono">curl -LsSf https://astral.sh/uv/install.sh | sh</code>）。仓库需可访问。
      </p>

      <div
        v-if="registrationWatch.state.value !== 'idle'"
        class="mt-3 flex items-center gap-2 rounded-lg border px-3 py-2 text-xs"
        :class="{
          'border-amber-500/40 bg-amber-500/10 text-amber-700 dark:text-amber-300':
            registrationWatch.state.value === 'waiting',
          'border-emerald-500/40 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300':
            registrationWatch.state.value === 'registered',
          'border-border bg-muted/40 text-muted-foreground':
            registrationWatch.state.value === 'timeout',
        }"
      >
        <Icon
          v-if="registrationWatch.state.value === 'waiting'"
          name="refresh"
          :size="13"
          class="animate-spin"
        />
        <Icon v-else-if="registrationWatch.state.value === 'registered'" name="check" :size="13" />
        <Icon v-else name="info" :size="13" />
        <span class="flex-1">
          <template v-if="registrationWatch.state.value === 'waiting'">
            等待 <code class="font-mono">{{ cfg.receiverId }}</code> 注册（60 秒内自动检测）…
          </template>
          <template v-else-if="registrationWatch.state.value === 'registered'">
            <code class="font-mono">{{ cfg.receiverId }}</code> 已注册
            <RouterLink
              :to="{ path: '/receivers', query: { id: cfg.receiverId } }"
              class="ml-1 underline underline-offset-2"
              @click="$emit('close')"
            >查看节点 →</RouterLink>
          </template>
          <template v-else>
            60 秒内未检测到注册。检查目标机器日志：
            <code class="font-mono">docker logs sathop-receiver</code>
          </template>
        </span>
      </div>
    </div>

    <div class="mt-5 flex justify-end gap-2">
      <Button type="button" @click="$emit('close')">关闭</Button>
    </div>
  </Modal>
</template>
