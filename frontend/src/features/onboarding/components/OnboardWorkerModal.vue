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
  DEFAULT_WORKER_DIR,
  type ExposeMode,
  hostDirPrestep,
  isAbsolutePath,
  isPrivateHost,
  workerDockerCompose,
  workerDockerRun,
  workerOpsHint,
  workerPublicUrl,
} from "@/features/onboarding/snippets";
import { useRegistrationWatch } from "@/features/onboarding/useRegistrationWatch";

defineEmits<{ close: [] }>();

const toast = useToast();

const workerId = ref(`worker-${Math.random().toString(36).slice(2, 8)}`);
const token = ref(getToken());
const orchUrl = ref(window.location.origin);
const exposeMode = ref<ExposeMode>("selfsigned");
const domain = ref("");
const ipAddress = ref("");
const hostPort = ref("");
const storagePort = ref(9000);
const dataDir = ref(DEFAULT_WORKER_DIR);
const capacity = ref(20);
const heartbeat = ref(15);
const downloadConcurrency = ref(1);
const showToken = ref(false);

type TabKey = "one-click" | "docker-run" | "compose";
const activeTab = ref<TabKey>("one-click");
const tabs = computed<Array<{ key: TabKey; label: string; hint: string }>>(() => [
  {
    key: "one-click",
    label: "一键部署",
    hint: "适合云服务器，自动检测 IP / 端口 / 生成 ID",
  },
  {
    key: "docker-run",
    label: "Docker Run",
    hint: exposeMode.value === "caddy" ? "两条命令：worker + caddy" : "一条命令",
  },
  {
    key: "compose",
    label: "Docker Compose",
    hint: "保存为 docker-compose.yml 后 docker compose up -d",
  },
]);

const cfg = computed(() => ({
  workerId: workerId.value.trim() || "worker-unnamed",
  token: token.value,
  orchUrl: orchUrl.value.trim().replace(/\/api\/?$/, ""),
  exposeMode: exposeMode.value,
  domain: domain.value.trim(),
  ipAddress: ipAddress.value.trim(),
  hostPort: hostPort.value.trim(),
  storagePort: storagePort.value,
  dataDir: dataDir.value.trim() || DEFAULT_WORKER_DIR,
  capacity: capacity.value,
  heartbeat: heartbeat.value,
  downloadConcurrency: downloadConcurrency.value,
}));

const computedPublicUrl = computed(() => workerPublicUrl(cfg.value));

// Direct HTTP mode leaks pulls in plaintext over the wire, so we restrict
// the operator to internal addressing. Caddy/selfsigned are TLS-protected
// and may legitimately use public IPs / domains.
const directHostInvalid = computed(
  () =>
    cfg.value.exposeMode === "direct" &&
    cfg.value.hostPort.length > 0 &&
    !isPrivateHost(cfg.value.hostPort),
);

// Relative dataDir is catastrophic for worker — the self-signed cert lives
// under data/tls and would silently re-generate every time docker run fires
// from a different PWD, invalidating every receiver's trust bundle.
const dataDirRelative = computed(() => !isAbsolutePath(cfg.value.dataDir));

const oneClickSnippet = computed(() => {
  const orch = cfg.value.orchUrl || "http://orch.example.com:8000";
  const tok = cfg.value.token || "YOUR_TOKEN";
  return `export SATHOP_ORCH_URL="${orch}"
export SATHOP_TOKEN="${tok}"
curl -fsSL https://raw.githubusercontent.com/imutum/sathop/main/deploy/worker/setup.sh | bash`;
});

const snippet = computed(() => {
  switch (activeTab.value) {
    case "one-click":
      return oneClickSnippet.value;
    case "docker-run":
      return `${workerDockerRun(cfg.value)}\n\n${workerOpsHint()}`;
    case "compose":
      return workerDockerCompose(cfg.value);
  }
  return "";
});

const valid = computed(() => {
  if (activeTab.value === "one-click") return !!(cfg.value.token && cfg.value.orchUrl);
  if (!cfg.value.workerId || !cfg.value.token || !cfg.value.orchUrl) return false;
  if (cfg.value.exposeMode === "caddy") return cfg.value.domain.length > 0;
  if (cfg.value.exposeMode === "selfsigned") return cfg.value.ipAddress.length > 0;
  return cfg.value.hostPort.length > 0 && !directHostInvalid.value;
});

// After-copy registration watcher. Shares the global TanStack Query cache,
// so SSE-driven invalidation (useLiveStream) refetches automatically when
// the orchestrator publishes a `workers` scope nudge — no extra polling.
const workersQuery = useQuery({ queryKey: [...K.workers], queryFn: API.workers });
const registrationWatch = useRegistrationWatch(
  computed(() => cfg.value.workerId),
  workersQuery.data,
  (w, id) => w.worker_id === id,
);

async function copySnippet() {
  await navigator.clipboard.writeText(snippet.value);
  toast.success("已复制到剪贴板");
  registrationWatch.start();
}
</script>

<template>
  <Modal width-class="w-[min(880px,95vw)]" @close="$emit('close')">
    <h2 class="mb-1 text-lg font-semibold">接入新工作节点</h2>
    <p class="mb-4 text-xs text-muted-foreground">
      选择部署方式 → 填参数 → 复制命令到目标机器执行
    </p>

    <Tabs v-model="activeTab" class="mb-4">
      <TabsList>
        <TabsTrigger v-for="t in tabs" :key="t.key" :value="t.key">
          {{ t.label }}
        </TabsTrigger>
      </TabsList>
    </Tabs>

    <Alert v-if="activeTab === 'one-click'" class="mb-4">
      <AlertDescription class="space-y-1 text-2xs">
        <div class="text-xs font-medium text-foreground">一键部署说明</div>
        <div>自动检测公网 IP，生成随机 Worker ID，使用自签证书</div>
        <div>端口自动选择：443 → 8443 → 9443（选第一个空闲的）</div>
        <div>数据目录：<code class="font-mono">/var/lib/sathop/worker</code></div>
        <div>只需填写 Orchestrator URL 和 Token，其余全自动</div>
      </AlertDescription>
    </Alert>

    <div class="grid grid-cols-1 gap-3 text-sm md:grid-cols-2">
      <div v-if="activeTab !== 'one-click'">
        <Label for="ow-id">Worker ID</Label>
        <Input id="ow-id" v-model="workerId" placeholder="worker-xxx" class="font-mono text-xs" />
      </div>
      <div v-if="activeTab !== 'one-click'">
        <Label for="ow-data">数据目录（host 绝对路径）</Label>
        <Input id="ow-data" v-model="dataDir" :placeholder="DEFAULT_WORKER_DIR" class="font-mono text-xs" />
      </div>
      <div class="md:col-span-2">
        <Label for="ow-orch">Orchestrator URL</Label>
        <Input
          id="ow-orch"
          v-model="orchUrl"
          placeholder="http://orch.example.com:8765"
          class="font-mono text-xs"
        />
      </div>
      <div class="md:col-span-2">
        <Label for="ow-token">Token</Label>
        <div class="relative">
          <Input
            id="ow-token"
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
      </div>
    </div>

    <div v-if="activeTab !== 'one-click'" class="mt-3">
      <Label>暴露方式</Label>
      <div class="mt-1 grid grid-cols-1 gap-1 rounded-md border border-border bg-muted/40 p-0.5 md:grid-cols-3">
        <button
          type="button"
          class="rounded px-3 py-1.5 text-xs font-medium transition-colors"
          :class="exposeMode === 'selfsigned' ? 'bg-background text-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground'"
          @click="exposeMode = 'selfsigned'"
        >
          自签 IP + HTTPS（内网，推荐）
        </button>
        <button
          type="button"
          class="rounded px-3 py-1.5 text-xs font-medium transition-colors"
          :class="exposeMode === 'caddy' ? 'bg-background text-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground'"
          @click="exposeMode = 'caddy'"
        >
          Caddy + HTTPS（公网域名）
        </button>
        <button
          type="button"
          class="rounded px-3 py-1.5 text-xs font-medium transition-colors"
          :class="exposeMode === 'direct' ? 'bg-background text-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground'"
          @click="exposeMode = 'direct'"
        >
          直接 HTTP（不加密）
        </button>
      </div>

      <div v-if="exposeMode === 'selfsigned'" class="mt-3">
        <Label for="ow-ip">Worker 主机 IP[:端口]</Label>
        <Input
          id="ow-ip"
          v-model="ipAddress"
          placeholder="192.168.1.50  或  192.168.1.50:8443"
          class="font-mono text-xs"
        />
        <p class="mt-1 text-2xs text-muted-foreground">
          Worker 自动生成 IP SAN 自签证书，无需 Caddy/域名。省略端口 ⇒ 默认 443；填
          <code class="font-mono">:8443</code> 等可走高位端口（自签证书与端口无关，仅绑 IP）。Public URL =
          <code class="font-mono">{{ computedPublicUrl }}</code>
        </p>
      </div>
      <div v-else-if="exposeMode === 'caddy'" class="mt-3">
        <Label for="ow-domain">域名</Label>
        <Input
          id="ow-domain"
          v-model="domain"
          placeholder="sathopworker.example.com"
          class="font-mono text-xs"
        />
        <p class="mt-1 text-2xs text-muted-foreground">
          Caddy 自动签发 Let's Encrypt 证书。Public URL =
          <code class="font-mono">{{ computedPublicUrl }}</code>
        </p>
      </div>
      <div v-else class="mt-3">
        <Label for="ow-host">主机:端口</Label>
        <Input
          id="ow-host"
          v-model="hostPort"
          :placeholder="`192.168.1.50:${storagePort}`"
          class="font-mono text-xs"
        />
        <p class="mt-1 text-2xs text-muted-foreground">
          Receiver 直接 HTTP 拉取，不加密 → 仅限内网 IP。Public URL =
          <code class="font-mono">{{ computedPublicUrl }}</code>
        </p>
        <Alert v-if="directHostInvalid" variant="destructive" class="mt-2">
          <AlertDescription class="text-2xs">
            直接 HTTP 模式必须使用内网 IP（10.x / 172.16–31.x / 192.168.x / 127.x / 100.64–127.x / IPv6 ULA 等）。明文 HTTP 在公网上会让拉取流量完全暴露 — 改用「自签 IP + HTTPS」或「Caddy + 域名」即可加密
          </AlertDescription>
        </Alert>
      </div>
    </div>

    <Alert v-if="dataDirRelative && activeTab !== 'one-click'" variant="destructive" class="mt-3">
      <AlertDescription class="text-2xs">
        相对路径会被锚定到 <code class="font-mono">docker run</code> 的当前目录——换个目录复制粘贴就会写到别处，<code class="font-mono">data/tls/</code> 下的自签证书也会随之重新生成，所有接收端的信任清单立刻失效。建议使用绝对路径（例如 <code class="font-mono">{{ DEFAULT_WORKER_DIR }}</code>）
      </AlertDescription>
    </Alert>

    <p v-if="activeTab !== 'one-click'" class="mt-2 text-2xs text-muted-foreground">
      命令统一假设 bash 兼容 shell（Linux / macOS / WSL / Git Bash）。Windows 用户请在 WSL 或 Git Bash 中执行——<code class="font-mono">$(id -u)</code>、<code class="font-mono">$(pwd)</code>、<code class="font-mono">\</code> 续行均为 bash 语法
    </p>

    <details v-if="activeTab !== 'one-click'" class="mt-3 rounded-lg border border-border bg-muted/40 px-3 py-2.5">
      <summary class="cursor-pointer text-xs font-medium text-muted-foreground transition-colors hover:text-foreground">
        高级：容量 / 心跳 / 并发 / 端口
      </summary>
      <div class="mt-2 grid grid-cols-2 gap-3 md:grid-cols-4">
        <div>
          <Label for="ow-cap">并发容量</Label>
          <Input id="ow-cap" v-model.number="capacity" type="number" min="1" max="200" />
        </div>
        <div>
          <Label for="ow-hb">心跳（秒）</Label>
          <Input id="ow-hb" v-model.number="heartbeat" type="number" min="1" max="120" />
        </div>
        <div>
          <Label for="ow-dlc">下载并发</Label>
          <Input
            id="ow-dlc"
            v-model.number="downloadConcurrency"
            type="number"
            min="1"
            max="32"
          />
        </div>
        <div>
          <Label for="ow-port">存储端口</Label>
          <Input id="ow-port" v-model.number="storagePort" type="number" min="1" max="65535" />
        </div>
      </div>
    </details>

    <Alert v-if="!valid" variant="destructive" class="mt-4">
      <AlertDescription>
        Worker ID / Token / Orchestrator URL /
        {{ exposeMode === "caddy" ? "域名" : exposeMode === "selfsigned" ? "Worker 主机 IP" : "主机:端口" }}
        都不能为空
      </AlertDescription>
    </Alert>

    <div v-if="exposeMode === 'selfsigned'" class="mt-4">
      <Alert>
        <AlertDescription class="space-y-1 text-2xs">
          <div class="text-xs font-medium text-foreground">自签 IP HTTPS 模式工作原理：</div>
          <div>1. Worker 启动时用 Python <code class="font-mono">cryptography</code> 生成 IP SAN 自签证书（10 年有效期，持久化在 <code class="font-mono">data/tls/</code>）</div>
          <div>2. uvicorn 直接以该证书监听 :443，注册时把证书 PEM 当 ca_pem 上报到调度中心</div>
          <div>3. 接收端启动时从调度中心拉取 CA 清单 → 精确验证 Worker 身份（中间人没有 worker 私钥就过不了 TLS）</div>
          <div class="font-medium text-foreground">
            ⚠️ 接收端 TLS 信任模式必须选「信任调度中心管理的 CA」，否则会握手失败
          </div>
          <div class="text-muted-foreground">
            零额外依赖：无需 Caddy、无需 Caddyfile、无需域名。换 Worker IP 时删掉 <code class="font-mono">data/tls/</code> 触发重新签发即可
          </div>
        </AlertDescription>
      </Alert>
    </div>

    <div v-else-if="exposeMode === 'caddy'" class="mt-4">
      <Alert>
        <AlertDescription class="space-y-1 text-2xs">
          <div class="text-xs font-medium text-foreground">Caddy + 域名 HTTPS 模式前置条件：</div>
          <div>1. 域名 <code class="font-mono">{{ cfg.domain || "<域名>" }}</code> 的 DNS A 记录已指向目标机器公网 IP</div>
          <div>2. 目标机器 80 / 443 端口对外开放（用于 ACME 证书签发与 HTTPS 接入）</div>
          <div>3. 第一次启动 Caddy 后约 30 秒自动签发 Let's Encrypt 证书</div>
        </AlertDescription>
      </Alert>
    </div>

    <div class="mt-5">

      <div v-if="activeTab === 'docker-run'" class="mt-3">
        <Alert>
          <AlertDescription class="space-y-1.5">
            <div class="text-xs">先在目标机器上确保数据目录存在并归当前用户：</div>
            <pre class="overflow-x-auto rounded bg-muted px-2 py-1.5 font-mono text-2xs">{{ hostDirPrestep(cfg.dataDir) }}</pre>
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
            等待 <code class="font-mono">{{ cfg.workerId }}</code> 注册（60 秒内自动检测）…
          </template>
          <template v-else-if="registrationWatch.state.value === 'registered'">
            <code class="font-mono">{{ cfg.workerId }}</code> 已注册
            <RouterLink
              :to="{ path: '/workers', query: { id: cfg.workerId } }"
              class="ml-1 underline underline-offset-2"
              @click="$emit('close')"
            >查看节点 →</RouterLink>
          </template>
          <template v-else>
            60 秒内未检测到注册。检查目标机器日志：
            <code class="font-mono">docker logs sathop-worker</code>
          </template>
        </span>
      </div>
    </div>

    <div class="mt-5 flex justify-end gap-2">
      <Button type="button" @click="$emit('close')">关闭</Button>
    </div>
  </Modal>
</template>
