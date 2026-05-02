<script setup lang="ts">
import { computed, ref } from "vue";
import { type Row, type Schema, emptyRow } from "@/features/batch/types";
import { Button } from "@/components/ui/button";
import { Alert, AlertDescription } from "@/components/ui/alert";
import Modal from "@/ui/Modal.vue";
import TextareaInput from "@/ui/TextareaInput.vue";

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

const text = ref(headers.value.join(",") + "\n");
const parseErr = ref<string | null>(null);

const dirty = computed(() => text.value.split(/\r?\n/).length > 2);

function doImport() {
  parseErr.value = null;
  const lines = text.value.split(/\r?\n/).filter((l) => l.trim() !== "");
  if (lines.length < 2) {
    parseErr.value = "至少需要一行表头 + 一行数据";
    return;
  }
  const delim = lines[0].includes("\t") ? "\t" : ",";
  const head = lines[0].split(delim).map((x) => x.trim());
  const missing = headers.value.filter((h) => !head.includes(h));
  if (missing.length && !missing.every((h) => OPTIONAL_SUFFIXES.some((suf) => h.endsWith(suf)))) {
    parseErr.value = `表头缺少：${missing.join(", ")}`;
    return;
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
  if (rows.length === 0) {
    parseErr.value = "没有解析到任何数据行";
    return;
  }
  emit("import", rows);
}
</script>

<template>
  <Modal width-class="w-[720px]" :z-index="60" :dirty="dirty" @close="emit('close')">
    <h3 class="font-display mb-2 text-base font-semibold">粘贴 CSV / TSV</h3>
    <div class="mb-3 text-[11px] text-muted-foreground">
      第一行必须是表头，列顺序不限。自动识别逗号或 Tab 分隔。
      <code class="font-mono text-[10px] text-muted-foreground">.size / .checksum / .credential</code> 列可选。
    </div>
    <TextareaInput
      v-model="text"
      rows="14"
      class="font-mono text-[11px]"
    />
    <div v-if="parseErr" class="mt-2"><Alert variant="destructive"><AlertDescription>{{ parseErr }}</AlertDescription></Alert></div>
    <div class="mt-3 flex justify-end gap-2">
      <Button @click="emit('close')">取消</Button>
      <Button variant="default" @click="doImport">导入</Button>
    </div>
  </Modal>
</template>
