<script setup lang="ts">
import { computed, ref } from "vue";
import { useToast } from "@/composables/useToast";
import { Icon } from "@/components/Icon";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Alert, AlertDescription } from "@/components/ui/alert";
import Modal from "@/ui/Modal.vue";
import {
  type Platform,
  linuxPrestep,
  receiverDockerCompose,
  receiverDockerRun,
  receiverOpsHint,
  receiverUvx,
} from "@/features/onboarding/snippets";

defineEmits<{ close: [] }>();

const toast = useToast();

const receiverId = ref(`recv-${Math.random().toString(36).slice(2, 8)}`);
const token = ref(localStorage.getItem("sathop.token") ?? "");
const orchUrl = ref(window.location.origin);
const outputDir = ref("./downloads");
const platform = ref<Platform>(navigator.userAgent.includes("Windows") ? "windows" : "linux");
const concurrent = ref(4);
const poll = ref(10);
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
  outputDir: outputDir.value.trim() || "./downloads",
  platform: platform.value,
  concurrent: concurrent.value,
  poll: poll.value,
}));

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

async function copySnippet() {
  await navigator.clipboard.writeText(snippet.value);
  toast.success("已复制到剪贴板");
}
</script>

<template>
  <Modal width-class="w-[min(820px,95vw)]" @close="$emit('close')">
    <h2 class="font-display mb-1 text-lg font-semibold">接入新接收端</h2>
    <p class="mb-5 text-xs text-muted-foreground">
      填好下面的参数 → 复制下方一段命令到目标机器执行 → 接收端会自动注册并开始拉取产物
    </p>

    <div class="grid grid-cols-1 gap-3 text-sm md:grid-cols-2">
      <div>
        <Label for="ob-id">Receiver ID</Label>
        <Input id="ob-id" v-model="receiverId" placeholder="recv-xxx" class="font-mono text-xs" />
      </div>
      <div>
        <Label for="ob-dir">输出目录</Label>
        <Input
          id="ob-dir"
          v-model="outputDir"
          placeholder="./downloads"
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
          <button
            type="button"
            class="absolute right-1 top-1/2 grid h-7 w-7 -translate-y-1/2 place-items-center rounded text-muted-foreground hover:bg-muted hover:text-foreground"
            :title="showToken ? '隐藏' : '显示'"
            @click="showToken = !showToken"
          >
            <Icon :name="showToken ? 'x' : 'info'" :size="13" />
          </button>
        </div>
        <p class="mt-1 text-2xs text-muted-foreground">
          默认填的是当前登录 token；要发给同事，可以换成另一个有权限的 token
        </p>
      </div>
      <div class="md:col-span-2">
        <Label>目标平台</Label>
        <div class="mt-1 inline-flex rounded-md border border-border bg-muted/40 p-0.5">
          <button
            type="button"
            class="rounded px-3 py-1 text-xs font-medium transition"
            :class="platform === 'linux' ? 'bg-background text-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground'"
            @click="platform = 'linux'"
          >
            Linux / macOS
          </button>
          <button
            type="button"
            class="rounded px-3 py-1 text-xs font-medium transition"
            :class="platform === 'windows' ? 'bg-background text-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground'"
            @click="platform = 'windows'"
          >
            Windows PowerShell
          </button>
        </div>
        <p class="mt-1 text-2xs text-muted-foreground">
          影响命令的续行符 (<code class="font-mono">\</code> vs
          <code class="font-mono">`</code>) 与 <code class="font-mono">--user $(id -u):$(id -g)</code> 的添加
        </p>
      </div>
    </div>

    <details class="mt-3 rounded-lg border border-border bg-muted/40 px-3 py-2.5">
      <summary class="cursor-pointer text-xs font-medium text-muted-foreground transition hover:text-foreground">
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
      <div class="flex items-end justify-between gap-3 border-b border-border">
        <div class="flex gap-1">
          <button
            v-for="t in tabs"
            :key="t.key"
            type="button"
            class="border-b-2 px-3 py-2 text-xs font-medium transition"
            :class="
              activeTab === t.key
                ? 'border-primary text-foreground'
                : 'border-transparent text-muted-foreground hover:text-foreground'
            "
            @click="activeTab = t.key"
          >
            {{ t.label }}
          </button>
        </div>
        <span class="pb-2 text-2xs text-muted-foreground">
          {{ tabs.find((t) => t.key === activeTab)?.hint }}
        </span>
      </div>

      <div v-if="activeTab === 'docker-run' && platform === 'linux'" class="mt-3">
        <Alert>
          <AlertDescription class="space-y-1.5">
            <div class="text-xs">先在目标机器上确保宿主目录存在并归当前用户：</div>
            <pre class="overflow-x-auto rounded bg-muted px-2 py-1.5 font-mono text-2xs">{{ linuxPrestep(cfg.outputDir) }}</pre>
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
    </div>

    <div class="mt-5 flex justify-end gap-2">
      <Button type="button" @click="$emit('close')">关闭</Button>
    </div>
  </Modal>
</template>
