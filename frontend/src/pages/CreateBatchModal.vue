<script setup lang="ts">
import { computed, reactive, ref, watch } from "vue";
import { useMutation, useQuery } from "@tanstack/vue-query";
import { API } from "../api";
import { clearCred, hasCred, loadCred, saveCred } from "../credCache";
import { useToast } from "../composables/useToast";
import {
  type CredDraft,
  type Row,
  type Schema,
  credDraftToApi,
  emptyCred,
  emptyRow,
  hasAnyInput,
  rowHasErrors,
  rowToGranule,
  validateRow,
} from "./createBatchTypes";
import ActionButton from "../ui/ActionButton.vue";
import Alert from "../ui/Alert.vue";
import FieldLabel from "../ui/FieldLabel.vue";
import Modal from "../ui/Modal.vue";
import SelectInput from "../ui/SelectInput.vue";
import TextareaInput from "../ui/TextareaInput.vue";
import TextInput from "../ui/TextInput.vue";
import CreateBatchCredentials from "./CreateBatchCredentials.vue";
import CreateBatchCsvModal from "./CreateBatchCsvModal.vue";
import CreateBatchGranuleTable from "./CreateBatchGranuleTable.vue";

const props = defineProps<{ initialBundle?: string }>();
const emit = defineEmits<{ close: []; created: [] }>();

const toast = useToast();

const batchId = ref("");
const name = ref("");
const bundleSel = ref(props.initialBundle ?? "");
const targetReceiver = ref("");
const envText = ref("");
const rows = ref<Row[]>([]);
const creds = reactive<Record<string, CredDraft>>({});
const remember = reactive<Record<string, boolean>>({});
const submitError = ref<string | null>(null);
const showCsv = ref(false);

const receivers = useQuery({ queryKey: ["receivers"], queryFn: API.receivers });
const bundles = useQuery({ queryKey: ["bundles"], queryFn: API.bundles });
const bundleDetail = useQuery({
  queryKey: computed(() => ["bundle-detail", bundleSel.value]),
  queryFn: () => {
    const [n, v] = bundleSel.value.split("@");
    return API.bundleDetail(n, v);
  },
  enabled: computed(() => !!bundleSel.value),
});

const schema = computed<Schema | null>(() => {
  const m = bundleDetail.data.value?.manifest;
  if (!m) return null;
  const raw = m.inputs as { slots?: Schema["slots"]; meta?: Schema["metaFields"] } | undefined;
  return { slots: raw?.slots ?? [], metaFields: raw?.meta ?? [] };
});

const requiredCreds = computed<string[]>(
  () => bundleDetail.data.value?.manifest.requirements?.credentials ?? [],
);

// Reset granule rows when bundle changes (slots/meta shape differs).
watch(
  () => [bundleSel.value, schema.value?.slots.length, schema.value?.metaFields.length],
  () => {
    rows.value = schema.value ? [emptyRow(schema.value.slots)] : [];
  },
);

// Hydrate credential drafts when the bundle's required-creds list changes.
// Cancellation guard mirrors the React effect: a stale fetch shouldn't
// stomp on a fresher one when the user picks bundles in quick succession.
watch(
  () => requiredCreds.value.join("|"),
  async () => {
    const names = requiredCreds.value;
    const expectedKey = names.join("|");
    const stored = await Promise.all(names.map((n) => loadCred(n)));
    if (requiredCreds.value.join("|") !== expectedKey) return;
    for (const k of Object.keys(creds)) delete creds[k];
    for (const k of Object.keys(remember)) delete remember[k];
    names.forEach((n, i) => {
      creds[n] = stored[i] ?? emptyCred();
      remember[n] = hasCred(n);
    });
  },
  { immediate: true },
);

const parsedEnv = computed<
  { ok: true; value: Record<string, string> } | { ok: false; error: string }
>(() => {
  const txt = envText.value.trim();
  if (!txt) return { ok: true, value: {} };
  try {
    const v = JSON.parse(txt);
    if (typeof v !== "object" || v === null || Array.isArray(v)) {
      return { ok: false, error: "必须是 JSON 对象 {KEY: value}" };
    }
    const out: Record<string, string> = {};
    for (const [k, val] of Object.entries(v)) out[k] = String(val);
    return { ok: true, value: out };
  } catch (e) {
    return { ok: false, error: (e as Error).message };
  }
});

const rowErrors = computed(() =>
  schema.value
    ? rows.value.map((r) => validateRow(r, schema.value!.slots, schema.value!.metaFields))
    : [],
);
const allRowsOk = computed(
  () => !!schema.value && rows.value.length > 0 && rowErrors.value.every((e) => !rowHasErrors(e)),
);

const credsPayload = computed(() =>
  Object.fromEntries(Object.entries(creds).map(([n, d]) => [n, credDraftToApi(n, d)])),
);

const credsValid = computed(() =>
  requiredCreds.value.every((n) => {
    const d = creds[n];
    if (!d) return false;
    return d.secret.trim() !== "" && (d.scheme !== "basic" || d.username.trim() !== "");
  }),
);

const create = useMutation({
  mutationFn: () =>
    API.createBatch({
      batch_id: batchId.value,
      name: name.value,
      bundle_ref: `orch:${bundleSel.value}`,
      target_receiver_id: targetReceiver.value || null,
      granules: rows.value.map((r) => rowToGranule(r, schema.value!.slots)),
      execution_env: parsedEnv.value.ok ? parsedEnv.value.value : {},
      credentials: credsPayload.value,
  }),
  onSuccess: (b) => {
    submitError.value = null;
    for (const n of requiredCreds.value) {
      const d = creds[n];
      if (remember[n] && d) {
        void saveCred(n, { scheme: d.scheme, username: d.username, secret: d.secret });
      } else if (hasCred(n)) {
        clearCred(n);
      }
    }
    toast.success(`已创建批次 "${b.name}"，共 ${rows.value.length} 条数据粒`);
    emit("created");
  },
  onError: (e: Error) => {
    submitError.value = e.message;
    toast.error(`创建失败：${e.message}`);
  },
});

const disabledReason = computed<string | null>(() => {
  if (create.isPending.value) return null;
  if (!batchId.value.trim()) return "请先填批次 ID";
  if (!name.value.trim()) return "请先填展示名称";
  if (!bundleSel.value) return "请先选择任务包";
  if (!allRowsOk.value) return "数据粒表格有未填或不合法的字段";
  if (!parsedEnv.value.ok) return "环境变量 JSON 不合法";
  if (!credsValid.value) return "凭证未填完";
  return null;
});

const canSubmit = computed(() => disabledReason.value === null && !create.isPending.value);

function rowHasDraftContent(row: Row) {
  return (
    row.granule_id.trim() !== "" ||
    Object.values(row.inputs).some((i) => i.url.trim() !== "" || i.filename.trim() !== "") ||
    Object.values(row.meta).some((v) => v.trim() !== "")
  );
}

function credentialsHaveDraftContent(drafts: Record<string, CredDraft>) {
  return Object.values(drafts).some((d) => d.username.trim() !== "" || d.secret.trim() !== "");
}

const dirty = computed(() => {
  return (
    batchId.value.trim() !== "" ||
    name.value.trim() !== "" ||
    bundleSel.value !== "" ||
    targetReceiver.value !== "" ||
    envText.value.trim() !== "" ||
    rows.value.some(rowHasDraftContent) ||
    credentialsHaveDraftContent(creds)
  );
});

function tryClose() {
  emit("close");
}

function submit() {
  if (canSubmit.value) create.mutate();
}

function onKeydown(e: KeyboardEvent) {
  if ((e.ctrlKey || e.metaKey) && e.key === "Enter" && canSubmit.value) {
    e.preventDefault();
    create.mutate();
  }
}

function onCsvImport(imported: Row[]) {
  rows.value = [
    ...rows.value.filter((r) => r.granule_id.trim() !== "" || hasAnyInput(r)),
    ...imported,
  ];
  showCsv.value = false;
}

function onCredChange(n: string, d: CredDraft) {
  creds[n] = d;
}
function onRememberChange(n: string, v: boolean) {
  remember[n] = v;
}
function onForget(n: string) {
  clearCred(n);
  creds[n] = emptyCred();
  remember[n] = false;
}
</script>

<template>
  <Modal width-class="w-[min(1200px,95vw)]" :dirty="dirty" @close="tryClose">
    <h2 class="font-display mb-1 text-lg font-semibold">新建任务</h2>
    <div class="mb-4 flex items-center gap-1.5 text-[11px] text-muted">
      <span>提示：</span>
      <kbd class="kbd">Ctrl</kbd>
      <span>+</span>
      <kbd class="kbd">Enter</kbd>
      <span>提交</span>
      <span class="text-border">·</span>
      <kbd class="kbd">Esc</kbd>
      <span>关闭</span>
    </div>
    <form @submit.prevent="submit" @keydown="onKeydown" class="space-y-3 text-sm">
      <div class="grid grid-cols-1 gap-3 md:grid-cols-3">
        <label class="block">
          <FieldLabel required>批次 ID</FieldLabel>
          <TextInput
            required
            v-model="batchId"
            placeholder="如 mod09a1-2024001"
            class="mt-1.5 font-mono text-xs"
          />
        </label>
        <label class="block">
          <FieldLabel required>展示名称</FieldLabel>
          <TextInput
            required
            v-model="name"
            placeholder="MOD09A1 2024 第 1 天"
            class="mt-1.5"
          />
        </label>
        <label class="block">
          <FieldLabel>目标接收端</FieldLabel>
          <SelectInput
            v-model="targetReceiver"
            class="mt-1.5"
          >
            <option value="">任意（由调度器决定）</option>
            <option
              v-for="r in receivers.data.value ?? []"
              :key="r.receiver_id"
              :value="r.receiver_id"
            >
              {{ r.receiver_id }}
            </option>
          </SelectInput>
        </label>
      </div>

      <label class="block">
        <FieldLabel required>任务包</FieldLabel>
        <SelectInput
          required
          v-model="bundleSel"
          class="mt-1.5 font-mono text-xs"
        >
          <option value="">-- 选择任务包 --</option>
          <option
            v-for="b in bundles.data.value ?? []"
            :key="`${b.name}@${b.version}`"
            :value="`${b.name}@${b.version}`"
          >
            {{ b.name }}@{{ b.version }}{{ b.description ? ` — ${b.description}` : "" }}
          </option>
        </SelectInput>
        <div v-if="(bundles.data.value ?? []).length === 0" class="mt-1 text-[11px] text-warning">
          尚无已注册任务包。先到"任务包"页上传一个 ZIP。
        </div>
      </label>

      <div
        v-if="bundleDetail.data.value && schema"
        class="rounded-lg border border-border bg-subtle/40 px-3 py-2 text-[11px] text-muted"
      >
        <div>
          入口：
          <span class="font-mono text-text">
            {{ bundleDetail.data.value.manifest.execution.entrypoint }}
          </span>
        </div>
        <div class="mt-0.5">
          依赖：{{ bundleDetail.data.value.manifest.requirements?.pip?.length ?? 0 }} 个 pip
          <template v-if="bundleDetail.data.value.manifest.requirements?.apt?.length">
            · {{ bundleDetail.data.value.manifest.requirements.apt.length }} 个 apt
          </template>
        </div>
      </div>

      <CreateBatchCredentials
        v-if="requiredCreds.length > 0"
        :names="requiredCreds"
        :drafts="creds"
        :remember="remember"
        @change="onCredChange"
        @remember-change="onRememberChange"
        @forget="onForget"
      />

      <CreateBatchGranuleTable
        v-if="schema"
        :schema="schema"
        :rows="rows"
        :errors="rowErrors"
        @update:rows="(r) => (rows = r)"
        @open-csv="showCsv = true"
      />

      <details class="rounded-lg border border-border bg-subtle/40 px-3 py-2.5">
        <summary class="cursor-pointer text-xs font-medium text-muted transition hover:text-text">
          高级：环境变量覆盖（可选，JSON 对象）
        </summary>
        <TextareaInput
          v-model="envText"
          :placeholder="'{\n  &quot;SATHOP_FACTOR&quot;: &quot;4&quot;\n}'"
          rows="3"
          class="mt-2 font-mono text-xs"
        />
        <div v-if="!parsedEnv.ok" class="mt-1 text-[11px] text-danger">
          JSON 错误：{{ parsedEnv.error }}
        </div>
      </details>

      <Alert v-if="submitError">
        <span class="whitespace-pre-wrap">{{ submitError }}</span>
      </Alert>

      <div class="flex justify-end gap-2 pt-2">
        <ActionButton type="button" @click="tryClose">取消</ActionButton>
        <ActionButton
          type="submit"
          tone="primary"
          :disabled="!canSubmit"
          :title="disabledReason ?? undefined"
          :pending="create.isPending.value"
          pending-label="提交中…"
        >
          提交 {{ rows.length > 0 ? `(${rows.length} 条)` : "" }}
        </ActionButton>
      </div>
    </form>

    <CreateBatchCsvModal
      v-if="showCsv && schema"
      :schema="schema"
      @close="showCsv = false"
      @import="onCsvImport"
    />
  </Modal>
</template>
