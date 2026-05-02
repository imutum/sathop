<script setup lang="ts">
import { type Row, type RowErrors, type Schema, emptyRow } from "@/features/batch/types";
import { requestConfirm } from "@/composables/useConfirm";
import CreateBatchCell from "@/features/batch/components/CreateBatchCell.vue";

const props = defineProps<{
  schema: Schema;
  rows: Row[];
  errors: RowErrors[];
}>();
const emit = defineEmits<{
  "update:rows": [r: Row[]];
  openCsv: [];
}>();

function patch(idx: number, fn: (r: Row) => Row) {
  emit(
    "update:rows",
    props.rows.map((r, i) => (i === idx ? fn(r) : r)),
  );
}

function addRow() {
  emit("update:rows", [...props.rows, emptyRow(props.schema.slots)]);
}

async function removeRow(idx: number) {
  const r = props.rows[idx];
  const hasContent =
    r.granule_id.trim() !== "" ||
    Object.values(r.inputs).some((i) => i.url.trim() || i.filename.trim()) ||
    Object.values(r.meta).some((v) => v.trim());
  if (
    hasContent &&
    !(await requestConfirm({
      title: `删除第 ${idx + 1} 行？`,
      description: "该行已经填写了内容，删除后无法从当前表格恢复。",
      confirmText: "删除行",
      tone: "danger",
    }))
  ) {
    return;
  }
  emit(
    "update:rows",
    props.rows.filter((_, i) => i !== idx),
  );
}
</script>

<template>
  <div>
    <div class="mb-2 flex items-center justify-between">
      <span class="text-xs text-muted-foreground">数据粒 · {{ rows.length }} 条</span>
      <div class="flex gap-1.5 text-xs">
        <button
          type="button"
          @click="emit('openCsv')"
          class="rounded-md border border-border bg-background px-2 py-1 text-muted-foreground transition hover:border-primary/40 hover:text-foreground"
        >
          粘贴 CSV
        </button>
        <button
          type="button"
          @click="addRow"
          class="rounded-md border border-border bg-background px-2 py-1 text-muted-foreground transition hover:border-primary/40 hover:text-foreground"
        >
          + 添加行
        </button>
      </div>
    </div>
    <div class="overflow-x-auto rounded-lg border border-border">
      <table class="w-full text-xs">
        <thead class="bg-muted/60 text-left text-mini font-semibold uppercase tracking-[0.10em] text-muted-foreground">
          <tr>
            <th class="px-2 py-1.5">granule_id</th>
            <th
              v-for="s in schema.slots"
              :key="s.name"
              class="px-2 py-1.5"
              :colspan="s.credential ? 2 : 3"
              :title="`product=${s.product}`"
            >
              {{ s.name }}
            </th>
            <th
              v-for="m in schema.metaFields"
              :key="m.name"
              class="px-2 py-1.5"
              :title="m.pattern ? `/${m.pattern}/` : ''"
            >
              {{ m.name }}
            </th>
            <th class="px-2 py-1.5"></th>
          </tr>
          <tr class="text-[10px] normal-case">
            <th></th>
            <template v-for="s in schema.slots" :key="`sub-${s.name}`">
              <th class="px-2 py-1 text-muted-foreground">url</th>
              <th class="px-2 py-1 text-muted-foreground">filename</th>
              <th v-if="!s.credential" class="px-2 py-1 text-muted-foreground">credential</th>
            </template>
            <th
              v-for="m in schema.metaFields"
              :key="`sub-meta-${m.name}`"
              class="px-2 py-1 text-muted-foreground"
            >
              {{ m.pattern ?? "—" }}
            </th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="(r, idx) in rows"
            :key="idx"
            class="border-t border-border align-top"
          >
            <td class="px-2 py-1">
              <CreateBatchCell
                :model-value="r.granule_id"
                @update:model-value="(v) => patch(idx, (row) => ({ ...row, granule_id: v }))"
                :error="errors[idx]?.granule_id"
                placeholder="唯一"
              />
            </td>
            <template v-for="s in schema.slots" :key="`cells-${idx}-${s.name}`">
              <td class="px-2 py-1">
                <CreateBatchCell
                  :model-value="r.inputs[s.name]?.url ?? ''"
                  @update:model-value="
                    (v) =>
                      patch(idx, (row) => ({
                        ...row,
                        inputs: {
                          ...row.inputs,
                          [s.name]: { ...row.inputs[s.name], url: v },
                        },
                      }))
                  "
                  :error="errors[idx]?.inputs[s.name]?.url"
                  placeholder="https://…"
                  mono
                />
              </td>
              <td class="px-2 py-1">
                <CreateBatchCell
                  :model-value="r.inputs[s.name]?.filename ?? ''"
                  @update:model-value="
                    (v) =>
                      patch(idx, (row) => ({
                        ...row,
                        inputs: {
                          ...row.inputs,
                          [s.name]: { ...row.inputs[s.name], filename: v },
                        },
                      }))
                  "
                  :error="errors[idx]?.inputs[s.name]?.filename"
                  placeholder="留空=自动"
                  mono
                />
              </td>
              <td v-if="!s.credential" class="px-2 py-1">
                <CreateBatchCell
                  :model-value="r.inputs[s.name]?.credential ?? ''"
                  @update:model-value="
                    (v) =>
                      patch(idx, (row) => ({
                        ...row,
                        inputs: {
                          ...row.inputs,
                          [s.name]: { ...row.inputs[s.name], credential: v },
                        },
                      }))
                  "
                  placeholder="凭证名（可空）"
                />
              </td>
            </template>
            <td v-for="m in schema.metaFields" :key="`meta-${idx}-${m.name}`" class="px-2 py-1">
              <CreateBatchCell
                :model-value="r.meta[m.name] ?? ''"
                @update:model-value="
                  (v) =>
                    patch(idx, (row) => ({ ...row, meta: { ...row.meta, [m.name]: v } }))
                "
                :error="errors[idx]?.meta[m.name]"
                :placeholder="m.pattern ?? ''"
              />
            </td>
            <td class="px-2 py-1 text-right">
              <button
                type="button"
                @click="removeRow(idx)"
                class="text-muted-foreground hover:text-danger"
              >
                ×
              </button>
            </td>
          </tr>
          <tr v-if="rows.length === 0">
            <td :colspan="99" class="px-4 py-4 text-center text-muted-foreground">
              还没有数据粒。点击 "+ 添加行" 或 "粘贴 CSV"。
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
