<script setup lang="ts">
import { computed } from "vue";
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
import Modal from "@/ui/Modal.vue";

const props = defineProps<{ schema: Schema }>();
const emit = defineEmits<{ close: []; import: [rows: Row[]] }>();

// `<slot>.size` and `<slot>.checksum` are emitted in the template so power
// users see the slots they can fill — but treated as optional during parse,
// like `<slot>.credential`. Without checksum, the worker skips sha256 verify.
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
  // Validate only on submit/blur — re-parsing on every keystroke is wasteful
  // for the multi-line CSV blob this textarea typically holds.
  validateOnMount: false,
});

const onSubmit = handleSubmit((vals) => {
  const r = parseCsv(vals.text);
  if (r.rows) emit("import", r.rows);
});
</script>

<template>
  <Modal width-class="w-[720px]" :z-index="60" :dirty="meta.dirty" @close="emit('close')">
    <h3 class="font-display mb-2 text-base font-semibold">粘贴 CSV / TSV</h3>
    <div class="mb-3 text-2xs text-muted-foreground">
      第一行必须是表头，列顺序不限。自动识别逗号或 Tab 分隔。
      <code class="font-mono text-3xs text-muted-foreground">.size / .checksum / .credential</code> 列可选。
    </div>
    <form @submit.prevent="onSubmit">
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
        <Button type="button" @click="emit('close')">取消</Button>
        <Button type="submit" variant="default">导入</Button>
      </div>
    </form>
  </Modal>
</template>
