<script setup lang="ts">
import { computed, reactive, ref, watch } from "vue";
import { useMutation, useQuery } from "@tanstack/vue-query";
import { useForm } from "vee-validate";
import { toTypedSchema } from "@vee-validate/zod";
import { z } from "zod";
import { API } from "@/api";
import { clearCred, hasCred, loadCred, saveCred } from "@/credCache";
import { useToast } from "@/composables/useToast";
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
} from "@/features/batch/types";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import Modal from "@/ui/Modal.vue";
import SelectInput from "@/ui/SelectInput.vue";
import CreateBatchCredentials from "@/features/batch/components/CreateBatchCredentials.vue";
import CreateBatchCsvModal from "@/features/batch/components/CreateBatchCsvModal.vue";
import CreateBatchGranuleTable from "@/features/batch/components/CreateBatchGranuleTable.vue";

const props = defineProps<{ initialBundle?: string }>();
const emit = defineEmits<{ close: []; created: [] }>();

const toast = useToast();

// Header fields (vee-validate + zod). The granule rows and credentials
// drafts have their own per-element validation patterns and stay
// imperative; the submit gate combines all three layers below.
const headerSchema = toTypedSchema(
  z.object({
    batchId: z.string().min(1, "请填批次 ID"),
    name: z.string().min(1, "请填展示名称"),
    bundleSel: z.string().min(1, "请选择任务包"),
    targetReceiver: z.string().optional(),
    envText: z
      .string()
      .optional()
      .refine((v) => {
        if (!v?.trim()) return true;
        try {
          const parsed = JSON.parse(v);
          return typeof parsed === "object" && parsed !== null && !Array.isArray(parsed);
        } catch {
          return false;
        }
      }, "环境变量必须是 JSON 对象 {KEY: value}"),
  }),
);

const { handleSubmit, meta: headerMeta, values: headerValues } = useForm({
  validationSchema: headerSchema,
  initialValues: {
    batchId: "",
    name: "",
    bundleSel: props.initialBundle ?? "",
    targetReceiver: "",
    envText: "",
  },
});

const rows = ref<Row[]>([]);
const creds = reactive<Record<string, CredDraft>>({});
const remember = reactive<Record<string, boolean>>({});
const submitError = ref<string | null>(null);
const showCsv = ref(false);

// Reactive references into header form values, used by downstream queries
// and watches without leaking the useForm internals.
const bundleSel = computed(() => headerValues.bundleSel ?? "");

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

// JSON validity is enforced by the zod schema; this computed only converts
// the validated string into the `Record<string, string>` payload shape.
const parsedEnv = computed<Record<string, string>>(() => {
  const txt = headerValues.envText?.trim() ?? "";
  if (!txt) return {};
  try {
    const v = JSON.parse(txt);
    if (typeof v !== "object" || v === null || Array.isArray(v)) return {};
    return Object.fromEntries(Object.entries(v).map(([k, val]) => [k, String(val)]));
  } catch {
    return {};
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
      batch_id: headerValues.batchId!,
      name: headerValues.name!,
      bundle_ref: `orch:${headerValues.bundleSel}`,
      target_receiver_id: headerValues.targetReceiver || null,
      granules: rows.value.map((r) => rowToGranule(r, schema.value!.slots)),
      execution_env: parsedEnv.value,
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

// Submit gate: header (vee-validate) + rows table + credentials drafts.
// `disabledReason` is the user-facing tooltip when the submit button is
// greyed; vee-validate covers header field errors via FormMessage.
const disabledReason = computed<string | null>(() => {
  if (create.isPending.value) return null;
  if (!headerMeta.value.valid) return "请先完成顶部表单";
  if (!allRowsOk.value) return "数据粒表格有未填或不合法的字段";
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

const dirty = computed(
  () =>
    headerMeta.value.dirty ||
    rows.value.some(rowHasDraftContent) ||
    credentialsHaveDraftContent(creds),
);

function tryClose() {
  emit("close");
}

const onSubmit = handleSubmit(() => {
  if (canSubmit.value) create.mutate();
});

function onKeydown(e: KeyboardEvent) {
  if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
    e.preventDefault();
    void onSubmit();
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
    <div class="mb-4 flex items-center gap-1.5 text-[11px] text-muted-foreground">
      <span>提示：</span>
      <kbd class="kbd">Ctrl</kbd>
      <span>+</span>
      <kbd class="kbd">Enter</kbd>
      <span>提交</span>
      <span class="text-border">·</span>
      <kbd class="kbd">Esc</kbd>
      <span>关闭</span>
    </div>
    <form @submit.prevent="onSubmit" @keydown="onKeydown" class="space-y-3 text-sm">
      <div class="grid grid-cols-1 gap-3 md:grid-cols-3">
        <FormField v-slot="{ componentField }" name="batchId">
          <FormItem>
            <FormLabel>批次 ID</FormLabel>
            <FormControl>
              <Input
                v-bind="componentField"
                placeholder="如 mod09a1-2024001"
                class="font-mono text-xs"
              />
            </FormControl>
            <FormMessage />
          </FormItem>
        </FormField>
        <FormField v-slot="{ componentField }" name="name">
          <FormItem>
            <FormLabel>展示名称</FormLabel>
            <FormControl>
              <Input v-bind="componentField" placeholder="MOD09A1 2024 第 1 天" />
            </FormControl>
            <FormMessage />
          </FormItem>
        </FormField>
        <FormField v-slot="{ componentField }" name="targetReceiver">
          <FormItem>
            <FormLabel>目标接收端</FormLabel>
            <FormControl>
              <SelectInput v-bind="componentField">
                <option value="">任意（由调度器决定）</option>
                <option
                  v-for="r in receivers.data.value ?? []"
                  :key="r.receiver_id"
                  :value="r.receiver_id"
                >
                  {{ r.receiver_id }}
                </option>
              </SelectInput>
            </FormControl>
            <FormMessage />
          </FormItem>
        </FormField>
      </div>

      <FormField v-slot="{ componentField }" name="bundleSel">
        <FormItem>
          <FormLabel>任务包</FormLabel>
          <FormControl>
            <SelectInput v-bind="componentField" class="font-mono text-xs">
              <option value="">-- 选择任务包 --</option>
              <option
                v-for="b in bundles.data.value ?? []"
                :key="`${b.name}@${b.version}`"
                :value="`${b.name}@${b.version}`"
              >
                {{ b.name }}@{{ b.version }}{{ b.description ? ` — ${b.description}` : "" }}
              </option>
            </SelectInput>
          </FormControl>
          <FormMessage />
          <div v-if="(bundles.data.value ?? []).length === 0" class="text-[11px] text-warning">
            尚无已注册任务包。先到"任务包"页上传一个 ZIP。
          </div>
        </FormItem>
      </FormField>

      <div
        v-if="bundleDetail.data.value && schema"
        class="rounded-lg border border-border bg-muted/40 px-3 py-2 text-[11px] text-muted-foreground"
      >
        <div>
          入口：
          <span class="font-mono text-foreground">
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

      <details class="rounded-lg border border-border bg-muted/40 px-3 py-2.5">
        <summary class="cursor-pointer text-xs font-medium text-muted-foreground transition hover:text-foreground">
          高级：环境变量覆盖（可选，JSON 对象）
        </summary>
        <FormField v-slot="{ componentField }" name="envText">
          <FormItem class="mt-2">
            <FormControl>
              <Textarea
                v-bind="componentField"
                :placeholder="'{\n  &quot;SATHOP_FACTOR&quot;: &quot;4&quot;\n}'"
                rows="3"
                class="font-mono text-xs"
              />
            </FormControl>
            <FormMessage />
          </FormItem>
        </FormField>
      </details>

      <Alert v-if="submitError" variant="destructive">
        <AlertDescription class="whitespace-pre-wrap">{{ submitError }}</AlertDescription>
      </Alert>

      <div class="flex justify-end gap-2 pt-2">
        <Button type="button" @click="tryClose">取消</Button>
        <Button
          type="submit"
          variant="default"
          :disabled="!canSubmit"
          :title="disabledReason ?? undefined"
          :pending="create.isPending.value"
          pending-label="提交中…"
        >
          提交 {{ rows.length > 0 ? `(${rows.length} 条)` : "" }}
        </Button>
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
