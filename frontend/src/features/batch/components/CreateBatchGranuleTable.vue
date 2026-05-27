<script setup lang="ts">
import { computed, nextTick, ref, watch } from "vue";
import { useVirtualizer } from "@tanstack/vue-virtual";
import { type Row, type RowErrors, type Schema, emptyRow, rowHasErrors } from "@/features/batch/types";
import { requestConfirm } from "@/composables/useConfirm";
import { Button } from "@/components/ui/button";
import { Icon } from "@/components/Icon";
import CreateBatchCell from "@/features/batch/components/CreateBatchCell.vue";

const ROW_HEIGHT = 38;
const PAGE_SIZE = 100;

const props = defineProps<{
  schema: Schema;
  rows: Row[];
  errors: RowErrors[];
}>();
const emit = defineEmits<{
  "update:rows": [r: Row[]];
  openCsv: [];
}>();

const scrollRef = ref<HTMLElement | null>(null);
const currentPage = ref(0);

const totalPages = computed(() => Math.max(1, Math.ceil(props.rows.length / PAGE_SIZE)));
const pageStart = computed(() => currentPage.value * PAGE_SIZE);
const pageEnd = computed(() => Math.min(pageStart.value + PAGE_SIZE, props.rows.length));
const pageRows = computed(() => props.rows.slice(pageStart.value, pageEnd.value));
const pageErrors = computed(() => props.errors.slice(pageStart.value, pageEnd.value));
const showPagination = computed(() => props.rows.length > PAGE_SIZE);

const firstErrorPage = computed(() => {
  if (!showPagination.value) return -1;
  for (let i = 0; i < props.errors.length; i++) {
    if (rowHasErrors(props.errors[i])) return Math.floor(i / PAGE_SIZE);
  }
  return -1;
});

function goPage(p: number) {
  currentPage.value = Math.max(0, Math.min(p, totalPages.value - 1));
}

watch(() => props.rows.length, () => {
  if (currentPage.value >= totalPages.value) {
    currentPage.value = Math.max(0, totalPages.value - 1);
  }
});

const virtualizer = useVirtualizer(
  computed(() => ({
    count: pageRows.value.length,
    getScrollElement: () => scrollRef.value,
    estimateSize: () => ROW_HEIGHT,
    overscan: 8,
  })),
);

const virtualRows = computed(() => virtualizer.value.getVirtualItems());
const totalHeight = computed(() => virtualizer.value.getTotalSize());
const padTop = computed(() => (virtualRows.value.length ? virtualRows.value[0].start : 0));
const padBottom = computed(() => {
  const items = virtualRows.value;
  return items.length ? totalHeight.value - items[items.length - 1].end : 0;
});

function globalIdx(localIdx: number): number {
  return pageStart.value + localIdx;
}

function patch(idx: number, fn: (r: Row) => Row) {
  emit(
    "update:rows",
    props.rows.map((r, i) => (i === idx ? fn(r) : r)),
  );
}

async function addRow() {
  emit("update:rows", [...props.rows, emptyRow(props.schema.slots)]);
  await nextTick();
  goPage(totalPages.value - 1);
  await nextTick();
  virtualizer.value.scrollToIndex(pageRows.value.length - 1, { align: "end" });
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
  await nextTick();
  if (currentPage.value >= totalPages.value) {
    goPage(totalPages.value - 1);
  }
}

function measureRow(el: unknown) {
  if (el instanceof Element) virtualizer.value.measureElement(el);
}
</script>

<template>
  <div>
    <div class="mb-2 flex items-center justify-between">
      <span class="text-xs text-muted-foreground">
        数据粒 · {{ rows.length }} 条
        <template v-if="showPagination">（显示 {{ pageStart + 1 }}–{{ pageEnd }}）</template>
      </span>
      <div class="flex gap-1.5">
        <Button
          type="button"
          variant="outline"
          size="xs"
          class="text-muted-foreground hover:text-foreground"
          @click="emit('openCsv')"
        >
          导入 CSV
        </Button>
        <Button
          type="button"
          variant="outline"
          size="xs"
          class="text-muted-foreground hover:text-foreground"
          @click="addRow"
        >
          <Icon name="plus" :size="11" />
          添加行
        </Button>
      </div>
    </div>
    <div
      ref="scrollRef"
      class="max-h-[420px] overflow-auto rounded-lg border border-border"
    >
      <table class="w-full text-xs">
        <thead class="sticky top-0 z-10 bg-muted text-left text-mini font-semibold tracking-label text-muted-foreground">
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
          <tr class="text-3xs normal-case">
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
          <tr v-if="padTop > 0" aria-hidden="true">
            <td colspan="99" :style="{ height: `${padTop}px`, padding: 0 }"></td>
          </tr>
          <tr
            v-for="vItem in virtualRows"
            :key="vItem.index"
            :data-index="vItem.index"
            :ref="measureRow"
            class="border-t border-border align-top"
          >
            <td class="px-2 py-1">
              <CreateBatchCell
                :model-value="pageRows[vItem.index].granule_id"
                @update:model-value="(v) => patch(globalIdx(vItem.index), (row) => ({ ...row, granule_id: v }))"
                :error="pageErrors[vItem.index]?.granule_id"
                placeholder="唯一"
              />
            </td>
            <template v-for="s in schema.slots" :key="`cells-${vItem.index}-${s.name}`">
              <td class="px-2 py-1">
                <CreateBatchCell
                  :model-value="pageRows[vItem.index].inputs[s.name]?.url ?? ''"
                  @update:model-value="
                    (v) =>
                      patch(globalIdx(vItem.index), (row) => ({
                        ...row,
                        inputs: {
                          ...row.inputs,
                          [s.name]: { ...row.inputs[s.name], url: v },
                        },
                      }))
                  "
                  :error="pageErrors[vItem.index]?.inputs[s.name]?.url"
                  placeholder="https://…"
                  mono
                />
              </td>
              <td class="px-2 py-1">
                <CreateBatchCell
                  :model-value="pageRows[vItem.index].inputs[s.name]?.filename ?? ''"
                  @update:model-value="
                    (v) =>
                      patch(globalIdx(vItem.index), (row) => ({
                        ...row,
                        inputs: {
                          ...row.inputs,
                          [s.name]: { ...row.inputs[s.name], filename: v },
                        },
                      }))
                  "
                  :error="pageErrors[vItem.index]?.inputs[s.name]?.filename"
                  placeholder="留空=自动"
                  mono
                />
              </td>
              <td v-if="!s.credential" class="px-2 py-1">
                <CreateBatchCell
                  :model-value="pageRows[vItem.index].inputs[s.name]?.credential ?? ''"
                  @update:model-value="
                    (v) =>
                      patch(globalIdx(vItem.index), (row) => ({
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
            <td v-for="m in schema.metaFields" :key="`meta-${vItem.index}-${m.name}`" class="px-2 py-1">
              <CreateBatchCell
                :model-value="pageRows[vItem.index].meta[m.name] ?? ''"
                @update:model-value="
                  (v) =>
                    patch(globalIdx(vItem.index), (row) => ({ ...row, meta: { ...row.meta, [m.name]: v } }))
                "
                :error="pageErrors[vItem.index]?.meta[m.name]"
                :placeholder="m.pattern ?? ''"
              />
            </td>
            <td class="px-2 py-1 text-right">
              <Button
                type="button"
                variant="ghost"
                size="icon-sm"
                aria-label="删除该行"
                title="删除该行"
                class="h-6 w-6 text-muted-foreground hover:bg-danger/10 hover:text-danger"
                @click="removeRow(globalIdx(vItem.index))"
              >
                <Icon name="x" :size="12" :stroke-width="2.4" />
              </Button>
            </td>
          </tr>
          <tr v-if="padBottom > 0" aria-hidden="true">
            <td colspan="99" :style="{ height: `${padBottom}px`, padding: 0 }"></td>
          </tr>
          <tr v-if="rows.length === 0">
            <td colspan="99" class="px-4 py-4 text-center text-muted-foreground">
              还没有数据粒。点击 "+ 添加行" 或 "导入 CSV"。
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <div v-if="showPagination" class="mt-2 flex items-center justify-center gap-2 text-xs text-muted-foreground">
      <Button
        type="button"
        variant="ghost"
        size="icon-sm"
        :disabled="currentPage === 0"
        aria-label="上一页"
        @click="goPage(currentPage - 1)"
      >
        <Icon name="chevronLeft" :size="14" />
      </Button>
      <span class="tabular-nums">
        第 {{ currentPage + 1 }} / {{ totalPages }} 页
      </span>
      <Button
        type="button"
        variant="ghost"
        size="icon-sm"
        :disabled="currentPage >= totalPages - 1"
        aria-label="下一页"
        @click="goPage(currentPage + 1)"
      >
        <Icon name="chevronRight" :size="14" />
      </Button>
      <Button
        v-if="firstErrorPage >= 0 && firstErrorPage !== currentPage"
        type="button"
        variant="outline"
        size="xs"
        class="ml-2 text-danger hover:text-danger"
        @click="goPage(firstErrorPage)"
      >
        第 {{ firstErrorPage + 1 }} 页有错误
      </Button>
    </div>
  </div>
</template>
