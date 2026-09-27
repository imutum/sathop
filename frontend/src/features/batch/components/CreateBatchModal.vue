<script setup lang="ts">
import { computed, reactive, ref, shallowRef, watch } from "vue";
import { useMutation, useQuery } from "@tanstack/vue-query";
import { useForm } from "vee-validate";
import { toTypedSchema } from "@vee-validate/zod";
import { API } from "@/api";
import type { TaskTemplate } from "@/serviceWorkflows";
import { requestConfirm } from "@/composables/useConfirm";
import TaskTemplatePicker from "./TaskTemplatePicker.vue";
import { K } from "@/queryKeys";
import { createBatchHeaderSchema } from "@/features/batch/schemas";
import { clearCred, hasCred, loadCred, saveCred } from "@/credCache";
import { useToast } from "@/composables/useToast";
import {
  type CredDraft,
  credentialsAreValid,
  credentialsHaveDraftContent,
  credentialsPayload,
  emptyCred,
} from "@/features/batch/credentials";
import { parseExecutionEnv, rowToGranule } from "@/features/batch/serialization";
import { type Row, type Schema, emptyRow, hasAnyInput, rowHasDraftContent } from "@/features/batch/types";
import { useBatchRowValidation } from "@/features/batch/useBatchRowValidation";
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

const { handleSubmit, setFieldValue, meta: headerMeta, values: headerValues } = useForm({
  validationSchema: toTypedSchema(createBatchHeaderSchema),
  initialValues: {
    name: "",
    bundleSel: props.initialBundle ?? "",
    targetReceiver: "",
    envText: "",
  },
});

const rows = shallowRef<Row[]>([]);
const creds = reactive<Record<string, CredDraft>>({});
const remember = reactive<Record<string, boolean>>({});
const submitError = ref<string | null>(null);
const showCsv = ref(false);

const bundleSel = computed(() => headerValues.bundleSel ?? "");

const receivers = useQuery({ queryKey: [...K.receivers], queryFn: API.receivers });
const bundles = useQuery({ queryKey: [...K.bundles], queryFn: API.bundles });
const bundleDetail = useQuery({
  queryKey: computed(() => [...K.bundleDetail, bundleSel.value]),
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

watch(
  () => [bundleSel.value, schema.value?.slots.length, schema.value?.metaFields.length],
  () => {
    rows.value = schema.value ? [emptyRow(schema.value.slots)] : [];
  },
);

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

const parsedEnv = computed(() => parseExecutionEnv(headerValues.envText));

const { rowErrors, allRowsOk } = useBatchRowValidation(rows, schema);

const credsPayload = computed(() => credentialsPayload(creds));

const credsValid = computed(() => credentialsAreValid(requiredCreds.value, creds));

const create = useMutation({
  mutationFn: () =>
    API.createBatch({
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

const disabledReason = computed<string | null>(() => {
  if (create.isPending.value) return null;
  if (!headerMeta.value.valid) return "请先完成顶部表单";
  if (!allRowsOk.value) return "数据粒表格有未填或不合法的字段";
  if (!credsValid.value) return "凭证未填完";
  return null;
});

const canSubmit = computed(() => disabledReason.value === null && !create.isPending.value);

const dirty = computed(
  () =>
    headerMeta.value.dirty ||
    rows.value.some(rowHasDraftContent) ||
    credentialsHaveDraftContent(creds),
);

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

async function applyTemplate(template: TaskTemplate) {
  const bundle = template.bundle_ref.replace(/^orch:/, "");
  if (!bundles.data.value?.some(b => `${b.name}@${b.version}` === bundle)) {
    toast.error("模板引用的任务包不存在，请上传对应版本或更新模板");
    return;
  }
  if (template.target_receiver_id && !receivers.data.value?.some(r => r.receiver_id === template.target_receiver_id)) {
    toast.error("模板引用的接收端不存在，请更新模板");
    return;
  }
  if (dirty.value) {
    const confirmed = await requestConfirm({
      title: "套用模板配置？",
      description: "将替换任务包、接收端和环境变量。切换任务包时，已填的输入表格会清空。批次名称保持不变。",
      confirmText: "套用配置",
    });
    if (!confirmed) return;
  }
  setFieldValue("bundleSel", bundle);
  setFieldValue("targetReceiver", template.target_receiver_id ?? "");
  setFieldValue("envText", Object.keys(template.execution_env).length ? JSON.stringify(template.execution_env, null, 2) : "");
  toast.success("已套用模板，请填写批次名称与输入数据");
}
</script>

<template>
  <Modal v-slot="{ close }" title="新建批次" description="配置任务包与输入数据，提交后开始调度。" width-class="w-[1080px]" :dirty="dirty" @close="emit('close')">
    <TaskTemplatePicker
      :bundle-ref="`orch:${bundleSel}`"
      :receiver-id="headerValues.targetReceiver ?? ''"
      :env-text="headerValues.envText ?? ''"
      @apply="applyTemplate"
    />
    <form @submit.prevent="onSubmit" @keydown="onKeydown" class="space-y-5 text-sm">
      <section class="space-y-5" aria-labelledby="batch-settings-title">
        <h3 id="batch-settings-title" class="flex items-center gap-3 font-semibold"><span class="grid h-7 w-7 place-items-center rounded-full bg-primary/10 font-mono text-xs text-primary" aria-hidden="true">01</span>任务设置</h3>
        <div class="grid grid-cols-1 gap-4 md:grid-cols-[1.3fr_1.3fr_1fr]">
          <FormField v-slot="{ componentField }" name="name">
            <FormItem>
              <FormLabel>批次名称</FormLabel>
              <FormControl>
                <Input v-bind="componentField" placeholder="例如：九月地表温度交付" />
              </FormControl>
              <FormMessage />
            </FormItem>
          </FormField>
          <FormField v-slot="{ componentField }" name="bundleSel">
            <FormItem>
              <FormLabel>任务包</FormLabel>
              <FormControl>
                <SelectInput v-bind="componentField" class="font-mono text-xs">
                  <option value="">请选择任务包</option>
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
              <div v-if="bundles.isSuccess.value && bundles.data.value?.length === 0" class="text-2xs text-warning">
                暂无任务包，请先前往“任务包”页上传。
              </div>
            </FormItem>
          </FormField>
          <FormField v-slot="{ componentField }" name="targetReceiver">
            <FormItem>
              <FormLabel>目标接收端</FormLabel>
              <FormControl>
                <SelectInput v-bind="componentField">
                  <option value="">自动分配接收端</option>
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

        <details
          v-if="bundleDetail.data.value && schema"
          class="text-xs text-muted-foreground"
        >
          <summary class="w-fit cursor-pointer">任务包运行信息</summary>
          <div class="mt-2">
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
        </details>

        <CreateBatchCredentials
          v-if="requiredCreds.length > 0"
          :names="requiredCreds"
          :drafts="creds"
          :remember="remember"
          @change="onCredChange"
          @remember-change="onRememberChange"
          @forget="onForget"
        />

      </section>
      <section class="space-y-4 border-t pt-5" aria-labelledby="batch-inputs-title">
        <h3 id="batch-inputs-title" class="flex items-center gap-3 font-semibold"><span class="grid h-7 w-7 place-items-center rounded-full bg-primary/10 font-mono text-xs text-primary" aria-hidden="true">02</span>输入数据</h3>
        <CreateBatchGranuleTable v-if="schema"
          :schema="schema"
          :rows="rows"
          :errors="rowErrors"
          @update:rows="(r) => (rows = r)"
          @open-csv="showCsv = true"
        />
        <p v-else class="rounded-xl bg-muted/40 px-4 py-5 text-xs text-muted-foreground">选择任务包后，可填写数据链接或导入 CSV。</p>
      </section>

      <details class="rounded-lg border border-border bg-muted/40 px-3 py-2.5">
        <summary class="cursor-pointer text-xs font-medium text-muted-foreground transition-colors hover:text-foreground">
          高级设置：环境变量（JSON）
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

      <div class="modal-actions">
        <span class="mr-auto hidden self-center text-xs text-muted-foreground sm:inline">Ctrl / ⌘ + Enter 提交</span>
        <Button type="button" variant="outline" @click="close">取消</Button>
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
