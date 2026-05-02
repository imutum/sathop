<script setup lang="ts">
import { computed, ref } from "vue";
import { RouterLink, useRouter } from "vue-router";
import { API, type BundleDetail } from "@/api";
import { fmtBytes } from "@/ui/format";
import { requestConfirm } from "@/composables/useConfirm";
import { useToast } from "@/composables/useToast";
import ActionButton from "@/ui/ActionButton.vue";
import Alert from "@/ui/Alert.vue";
import Badge from "@/ui/Badge.vue";
import CopyButton from "@/ui/CopyButton.vue";
import Field from "@/ui/Field.vue";
import BundleFileBrowser from "@/features/bundle/components/BundleFileBrowser.vue";
import BundleSection from "@/features/bundle/components/BundleSection.vue";
import { Icon } from "@/ui/Icon";

const props = defineProps<{
  d: BundleDetail;
  pending: boolean;
  error: string | null;
}>();

const emit = defineEmits<{ delete: [] }>();

const router = useRouter();
const toast = useToast();

const m = computed(() => props.d.manifest);
const pip = computed(() => m.value.requirements?.pip ?? []);
const apt = computed(() => m.value.requirements?.apt ?? []);
const creds = computed(() => m.value.requirements?.credentials ?? []);
const env = computed(() => m.value.execution?.env ?? {});
const envEntries = computed(() => Object.entries(env.value));
const slots = computed(() => m.value.inputs?.slots ?? []);
const metaFields = computed(() => m.value.inputs?.meta ?? []);
const sharedFiles = computed(() => m.value.shared_files ?? []);

async function confirmDelete() {
  const ok = await requestConfirm({
    title: `删除任务包 ${props.d.name}@${props.d.version}？`,
    description: "此操作不可撤销；已引用它的批次会被服务端拒绝删除。",
    confirmText: "删除",
    tone: "danger",
  });
  if (ok) emit("delete");
}

function gotoNewBatch() {
  router.push(`/batches?bundle=${encodeURIComponent(`${props.d.name}@${props.d.version}`)}`);
}

const downloading = ref(false);
async function download() {
  downloading.value = true;
  try {
    await API.downloadBundle(props.d.name, props.d.version);
  } catch (e) {
    toast.error(`下载失败：${(e as Error).message}`);
  } finally {
    downloading.value = false;
  }
}
</script>

<template>
  <div class="space-y-5 text-sm">
    <div class="flex items-start justify-between gap-3">
      <div>
        <div class="flex items-center gap-2">
          <div class="font-mono text-[14px]">
            <span class="font-semibold">{{ d.name }}</span>
            <span class="text-legacy-muted">@{{ d.version }}</span>
          </div>
          <span v-if="d.in_use_count > 0" title="被批次引用 — 删除会被拒绝">
            <Badge tone="info">{{ d.in_use_count }} 批次引用中</Badge>
          </span>
        </div>
        <div v-if="d.description" class="mt-1.5 text-xs text-legacy-muted">{{ d.description }}</div>
      </div>
      <div class="flex items-center gap-2">
        <ActionButton tone="primary" @click="gotoNewBatch" title="跳转到批次页并预选此任务包">
          新建批次
          <Icon name="arrowRight" :size="13" />
        </ActionButton>
        <ActionButton
          @click="download"
          :pending="downloading"
          pending-label="下载中…"
          title="下载原始 ZIP 包"
        >
          <Icon name="download" :size="13" />
          下载
        </ActionButton>
        <ActionButton
          tone="danger"
          @click="confirmDelete"
          :pending="pending"
          pending-label="删除中…"
        >
          <Icon name="trash" :size="13" />
          删除
        </ActionButton>
      </div>
    </div>
    <Alert v-if="error">{{ error }}</Alert>

    <div class="grid grid-cols-2 gap-4 rounded-lg border border-border bg-legacy-subtle/40 p-4 text-xs sm:grid-cols-3">
      <Field label="SHA256">
        <span class="font-mono" :title="d.sha256">{{ d.sha256.slice(0, 16) }}…</span>
        <CopyButton :value="d.sha256" title="复制完整 SHA256" />
      </Field>
      <Field label="大小">
        <span class="font-mono tabular-nums">{{ fmtBytes(d.size) }}</span>
      </Field>
      <Field label="入口">
        <span class="break-all font-mono">{{ m.execution.entrypoint }}</span>
      </Field>
      <Field label="超时">
        {{ m.execution.timeout_sec ? `${m.execution.timeout_sec}s` : "默认" }}
      </Field>
      <Field label="输出目录">
        <span class="font-mono">{{ m.outputs.watch_dir }}</span>
      </Field>
      <Field label="输出扩展名">
        {{ m.outputs.extensions?.length ? m.outputs.extensions.join(", ") : "全部" }}
      </Field>
    </div>

    <BundleSection title="输入槽位 · slots" :count="slots.length">
      <div v-if="slots.length === 0" class="text-xs text-legacy-muted">未声明</div>
      <table v-else class="w-full font-mono text-[11.5px]">
        <thead class="text-legacy-muted">
          <tr class="border-b border-border/50">
            <th class="py-1.5 pr-3 text-left font-normal">name</th>
            <th class="py-1.5 pr-3 text-left font-normal">product</th>
            <th class="py-1.5 pr-3 text-left font-normal">filename_pattern</th>
            <th class="py-1.5 text-left font-normal">credential</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="s in slots" :key="s.name" class="border-t border-border/40">
            <td class="py-1.5 pr-3">{{ s.name }}</td>
            <td class="py-1.5 pr-3">{{ s.product }}</td>
            <td class="py-1.5 pr-3 break-all">{{ s.filename_pattern || "—" }}</td>
            <td class="py-1.5">{{ s.credential || "—" }}</td>
          </tr>
        </tbody>
      </table>
    </BundleSection>

    <BundleSection v-if="metaFields.length > 0" title="元字段 · meta" :count="metaFields.length">
      <table class="w-full font-mono text-[11.5px]">
        <thead class="text-legacy-muted">
          <tr class="border-b border-border/50">
            <th class="py-1.5 pr-3 text-left font-normal">name</th>
            <th class="py-1.5 text-left font-normal">pattern</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="f in metaFields" :key="f.name" class="border-t border-border/40">
            <td class="py-1.5 pr-3">{{ f.name }}</td>
            <td class="py-1.5 break-all">{{ f.pattern || "—" }}</td>
          </tr>
        </tbody>
      </table>
    </BundleSection>

    <BundleSection
      v-if="sharedFiles.length > 0"
      title="所需共享文件 · shared_files"
      :count="sharedFiles.length"
    >
      <div class="flex flex-wrap gap-1.5">
        <RouterLink
          v-for="n in sharedFiles"
          :key="n"
          to="/shared"
          class="inline-flex items-center gap-1 rounded-md bg-legacy-subtle px-2 py-1 font-mono text-[11px] text-legacy-muted transition hover:bg-legacy-accent-soft hover:text-legacy-accent"
          title="跳转到「共享文件」页"
        >
          {{ n }}
          <Icon name="arrowRight" :size="11" />
        </RouterLink>
      </div>
    </BundleSection>

    <BundleSection title="Python 依赖 · pip" :count="pip.length">
      <div v-if="pip.length === 0" class="text-xs text-legacy-muted">无</div>
      <ul v-else class="space-y-0.5 font-mono text-[11.5px]">
        <li v-for="p in pip" :key="p">{{ p }}</li>
      </ul>
    </BundleSection>

    <BundleSection v-if="apt.length > 0" title="系统依赖 · apt" :count="apt.length">
      <ul class="space-y-0.5 font-mono text-[11.5px]">
        <li v-for="p in apt" :key="p">{{ p }}</li>
      </ul>
    </BundleSection>

    <BundleSection
      v-if="envEntries.length > 0"
      title="默认环境变量"
      :count="envEntries.length"
    >
      <table class="w-full font-mono text-[11.5px]">
        <tbody>
          <tr v-for="[k, v] in envEntries" :key="k" class="border-t border-border/50">
            <td class="py-1.5 pr-3 text-legacy-muted">{{ k }}</td>
            <td class="break-all py-1.5">{{ String(v) }}</td>
          </tr>
        </tbody>
      </table>
    </BundleSection>

    <BundleSection v-if="creds.length > 0" title="所需凭证" :count="creds.length">
      <div class="flex flex-wrap gap-1.5">
        <Badge v-for="c in creds" :key="c" tone="info">{{ c }}</Badge>
      </div>
    </BundleSection>

    <BundleSection title="包内文件">
      <BundleFileBrowser :name="d.name" :version="d.version" />
    </BundleSection>
  </div>
</template>
