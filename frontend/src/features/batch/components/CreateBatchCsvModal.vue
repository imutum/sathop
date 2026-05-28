<script setup lang="ts">
import { computed, ref } from "vue";
import { useForm } from "vee-validate";
import { toTypedSchema } from "@vee-validate/zod";
import { z } from "zod";
import { type Row, type Schema, emptyRow } from "@/features/batch/types";
import { Button } from "@/components/ui/button";
import {
  FormControl,
  FormField,
  FormItem,
  FormMessage,
} from "@/components/ui/form";
import { Textarea } from "@/components/ui/textarea";
import FilePicker from "@/components/FilePicker.vue";
import Modal from "@/ui/Modal.vue";

const MAX_FILE_SIZE = 200 * 1024 * 1024;

const props = defineProps<{ schema: Schema }>();
const emit = defineEmits<{ close: []; import: [rows: Row[]] }>();

const mode = ref<"paste" | "file">("paste");

const headers = computed(() => {
  const h = ["granule_id"];
  for (const s of props.schema.slots) {
    h.push(`${s.name}.url`, `${s.name}.filename`);
    if (!s.credential) h.push(`${s.name}.credential`);
    h.push(`${s.name}.size`, `${s.name}.checksum`);
  }
  for (const m of props.schema.metaFields) h.push(`meta.${m.name}`);
  return h;
});

const OPTIONAL_SUFFIXES = [".credential", ".size", ".checksum"];

function parseCsv(text: string): { rows?: Row[]; error?: string } {
  const lines = text.split(/\r?\n/).filter((l) => l.trim() !== "");
  if (lines.length < 2) return { error: "至少需要一行表头 + 一行数据" };
  const delim = lines[0].includes("\t") ? "\t" : ",";
  const head = lines[0].split(delim).map((x) => x.trim());
  const missing = headers.value.filter((h) => !head.includes(h));
  if (missing.length && !missing.every((h) => OPTIONAL_SUFFIXES.some((suf) => h.endsWith(suf)))) {
    return { error: `表头缺少：${missing.join(", ")}` };
  }
  const rows: Row[] = [];
  for (let i = 1; i < lines.length; i++) {
    const cells = lines[i].split(delim).map((x) => x.trim());
    const byHead: Record<string, string> = {};
    head.forEach((h, idx) => (byHead[h] = cells[idx] ?? ""));
    const row = emptyRow(props.schema.slots);
    row.granule_id = byHead["granule_id"] ?? "";
    for (const s of props.schema.slots) {
      row.inputs[s.name].url = byHead[`${s.name}.url`] ?? "";
      row.inputs[s.name].filename = byHead[`${s.name}.filename`] ?? "";
      const credHead = byHead[`${s.name}.credential`];
      if (credHead !== undefined) row.inputs[s.name].credential = credHead;
      const sizeHead = byHead[`${s.name}.size`];
      if (sizeHead !== undefined) row.inputs[s.name].size = sizeHead;
      const sumHead = byHead[`${s.name}.checksum`];
      if (sumHead !== undefined) row.inputs[s.name].checksum = sumHead;
    }
    for (const m of props.schema.metaFields) {
      row.meta[m.name] = byHead[`meta.${m.name}`] ?? "";
    }
    rows.push(row);
  }
  if (rows.length === 0) return { error: "没有解析到任何数据行" };
  return { rows };
}

async function readFileText(f: File): Promise<string> {
  const buf = await f.arrayBuffer();
  try {
    return new TextDecoder("utf-8", { fatal: true }).decode(buf);
  } catch {
    return new TextDecoder("gbk").decode(buf);
  }
}

// --- Paste mode ---

const validationSchema = computed(() =>
  toTypedSchema(
    z.object({
      text: z
        .string()
        .min(1, "请粘贴 CSV / TSV 内容")
        .superRefine((val, ctx) => {
          const r = parseCsv(val);
          if (r.error) {
            ctx.addIssue({ code: z.ZodIssueCode.custom, message: r.error });
          }
        }),
    }),
  ),
);

const { handleSubmit, meta } = useForm({
  validationSchema,
  initialValues: { text: headers.value.join(",") + "\n" },
  validateOnMount: false,
});

const onPasteSubmit = handleSubmit((vals) => {
  const r = parseCsv(vals.text);
  if (r.rows) emit("import", r.rows);
});

// --- File mode ---

const file = ref<File | null>(null);
const fileResult = ref<{ rows?: Row[]; error?: string } | null>(null);
const fileLoading = ref(false);
let fileGen = 0;

async function onFileChange(f: File | null) {
  file.value = f;
  fileResult.value = null;
  if (!f) return;
  if (f.size > MAX_FILE_SIZE) {
    fileResult.value = { error: `文件过大（${(f.size / 1024 / 1024).toFixed(1)} MB），上限 ${MAX_FILE_SIZE / 1024 / 1024} MB` };
    return;
  }
  const gen = ++fileGen;
  fileLoading.value = true;
  try {
    const text = await readFileText(f);
    if (gen !== fileGen) return;
    fileResult.value = parseCsv(text);
  } catch {
    if (gen !== fileGen) return;
    fileResult.value = { error: "文件读取失败" };
  } finally {
    if (gen === fileGen) fileLoading.value = false;
  }
}

function onFileImport() {
  if (fileResult.value?.rows) emit("import", fileResult.value.rows);
}

// v-show keeps both modes mounted, so dirty reflects either mode's state.
const dirty = computed(() => meta.value.dirty || !!file.value);
</script>

<template>
  <Modal width-class="w-[720px]" :z-index="60" :dirty="dirty" @close="emit('close')">
    <h3 class="mb-2 text-base font-semibold">导入 CSV / TSV</h3>
    <div class="mb-3 text-2xs text-muted-foreground">
      第一行必须是表头，列顺序不限。自动识别逗号或 Tab 分隔。
      <code class="font-mono text-3xs text-muted-foreground">.size / .checksum / .credential</code> 列可选。
    </div>

    <div class="mb-3 flex gap-1">
      <Button
        type="button"
        :variant="mode === 'paste' ? 'default' : 'outline'"
        size="xs"
        @click="mode = 'paste'"
      >
        粘贴文本
      </Button>
      <Button
        type="button"
        :variant="mode === 'file' ? 'default' : 'outline'"
        size="xs"
        @click="mode = 'file'"
      >
        选择文件
      </Button>
    </div>

    <form v-show="mode === 'paste'" @submit.prevent="onPasteSubmit">
      <FormField v-slot="{ componentField }" name="text">
        <FormItem>
          <FormControl>
            <Textarea
              v-bind="componentField"
              rows="14"
              class="font-mono text-2xs"
            />
          </FormControl>
          <FormMessage />
        </FormItem>
      </FormField>
      <div class="mt-3 flex justify-end gap-2">
        <Button type="button" variant="outline" @click="emit('close')">取消</Button>
        <Button type="submit" variant="default">导入</Button>
      </div>
    </form>

    <div v-show="mode === 'file'">
      <FilePicker
        :model-value="file"
        @update:model-value="onFileChange"
        accept=".csv,.tsv,.txt"
      />
      <div v-if="fileLoading" class="mt-2 text-xs text-muted-foreground">解析中…</div>
      <div v-else-if="fileResult?.error" class="mt-2 text-xs text-danger">{{ fileResult.error }}</div>
      <div v-else-if="fileResult?.rows" class="mt-2 text-xs text-muted-foreground">
        已解析 <span class="font-semibold text-foreground">{{ fileResult.rows.length.toLocaleString() }}</span> 条数据粒
      </div>
      <div class="mt-3 flex justify-end gap-2">
        <Button type="button" variant="outline" @click="emit('close')">取消</Button>
        <Button
          type="button"
          variant="default"
          :disabled="!fileResult?.rows || fileLoading"
          @click="onFileImport"
        >
          导入
        </Button>
      </div>
    </div>
  </Modal>
</template>
