<script setup lang="ts">
import type { GranuleRow, ProgressRow, GranuleState } from "@/api";
import { fmtAge, stateLabel } from "@/i18n";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import EmptyState from "@/components/EmptyState.vue";
import ErrorCell from "@/features/batch/components/ErrorCell.vue";
import GranuleEvents from "@/features/batch/components/GranuleEvents.vue";
import LatestProgressLine from "@/features/batch/components/LatestProgressLine.vue";
import ProgressTimeline from "@/features/batch/components/ProgressTimeline.vue";
import StageTimingStrip from "@/features/batch/components/StageTimingStrip.vue";

const props = defineProps<{
  rows: GranuleRow[];
  batchId: string;
  highlight: string | null;
  expanded: string | null;
  latestProgress: Record<string, ProgressRow>;
  cancellable: Set<GranuleState>;
  retryable: Set<GranuleState>;
  cancellingId?: string;
  retryingId?: string;
}>();

const emit = defineEmits<{
  rowRef: [id: string, el: Element | null];
  toggle: [id: string];
  cancel: [row: GranuleRow];
  retry: [id: string];
}>();

function stripBatchPrefix(gid: string) {
  return gid.startsWith(`${props.batchId}:`) ? gid.slice(props.batchId.length + 1) : gid;
}
</script>

<template>
  <!-- Narrow: stacked card per granule (lg+ uses the table below). -->
  <ul class="divide-y divide-border/60 lg:hidden">
    <li v-if="rows.length === 0" class="p-5">
      <EmptyState title="该筛选条件下没有数据粒" />
    </li>
    <template v-for="g in rows" :key="g.granule_id">
      <li
        :ref="(el) => emit('rowRef', g.granule_id, el as Element | null)"
        :class="[
          'space-y-3 p-4 transition',
          g.granule_id === highlight ? 'bg-accent/40' : '',
        ]"
      >
        <div class="flex items-start justify-between gap-3">
          <div class="min-w-0 flex-1">
            <button
              @click="emit('toggle', g.granule_id)"
              class="mr-1 text-muted-foreground hover:text-foreground"
              :title="expanded === g.granule_id ? '收起进度' : '展开进度'"
            >
              {{ expanded === g.granule_id ? "▾" : "▸" }}
            </button>
            <span class="break-all font-mono text-[11.5px]">{{ stripBatchPrefix(g.granule_id) }}</span>
            <LatestProgressLine
              v-if="latestProgress[g.granule_id]"
              :row="latestProgress[g.granule_id]"
            />
          </div>
          <div class="flex shrink-0 flex-wrap items-center gap-1">
            <Badge :tone="g.state" dot>{{ stateLabel(g.state) }}</Badge>
            <span
              v-if="g.objects_exhausted > 0"
              :title="`${g.objects_exhausted} 个产物超出 receiver 拉取重试上限，已停止派发`"
            >
              <Badge tone="error">{{ g.objects_exhausted }} 已放弃</Badge>
            </span>
          </div>
        </div>
        <div class="flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-muted-foreground">
          <span class="tabular-nums">重试 {{ g.retry_count }}</span>
          <span class="font-mono">
            领取方:
            <RouterLink
              v-if="g.leased_by"
              :to="`/workers?id=${encodeURIComponent(g.leased_by)}`"
              class="transition hover:text-primary"
              title="跳转到该 worker 卡片"
            >
              {{ g.leased_by }}
            </RouterLink>
            <template v-else>—</template>
          </span>
          <span>{{ fmtAge(g.updated_at) }}</span>
        </div>
        <div v-if="g.error" class="font-mono text-[11.5px] text-danger">
          <ErrorCell :error="g.error" />
        </div>
        <div
          v-if="cancellable.has(g.state) || retryable.has(g.state)"
          class="flex justify-end gap-1.5"
        >
          <Button
            v-if="cancellable.has(g.state)"
            variant="destructive"
            size="sm"
            :pending="cancellingId === g.granule_id"
            pending-label="取消"
            @click="emit('cancel', g)"
          >
            取消
          </Button>
          <Button
            v-if="retryable.has(g.state)"
            size="sm"
            :pending="retryingId === g.granule_id"
            pending-label="重试"
            @click="emit('retry', g.granule_id)"
          >
            重试
          </Button>
        </div>
        <div v-if="expanded === g.granule_id" class="space-y-3 rounded-md bg-muted/40 p-3">
          <StageTimingStrip :granule-id="g.granule_id" />
          <ProgressTimeline :granule-id="g.granule_id" />
          <GranuleEvents :granule-id="g.granule_id" :batch-id="batchId" />
        </div>
      </li>
    </template>
  </ul>

  <!-- lg+ : original table. -->
  <div class="hidden overflow-x-auto lg:block">
    <table class="w-full text-sm">
      <thead class="bg-muted/50 th-row">
        <tr>
          <th class="px-5 py-3">数据粒</th>
          <th class="px-2 py-3">状态</th>
          <th class="px-2 py-3">重试</th>
          <th class="px-2 py-3">领取方</th>
          <th class="px-2 py-3">更新</th>
          <th class="px-2 py-3">错误</th>
          <th class="px-5 py-3 text-right">操作</th>
        </tr>
      </thead>
      <tbody>
        <template v-for="g in rows" :key="g.granule_id">
          <tr
            :ref="(el) => emit('rowRef', g.granule_id, el as Element | null)"
            :class="[
              'border-t border-border/60 align-top transition hover:bg-muted/40',
              g.granule_id === highlight ? 'bg-accent/40' : '',
            ]"
          >
            <td class="px-5 py-2.5 font-mono text-[11.5px]">
              <button
                @click="emit('toggle', g.granule_id)"
                class="mr-1 inline-block w-3 text-muted-foreground hover:text-foreground"
                :title="expanded === g.granule_id ? '收起进度' : '展开进度'"
              >
                {{ expanded === g.granule_id ? "▾" : "▸" }}
              </button>
              {{ stripBatchPrefix(g.granule_id) }}
              <LatestProgressLine
                v-if="latestProgress[g.granule_id]"
                :row="latestProgress[g.granule_id]"
              />
            </td>
            <td class="px-2 py-2.5">
              <div class="flex flex-wrap items-center gap-1">
                <Badge :tone="g.state" dot>{{ stateLabel(g.state) }}</Badge>
                <span
                  v-if="g.objects_exhausted > 0"
                  :title="`${g.objects_exhausted} 个产物超出 receiver 拉取重试上限，已停止派发`"
                >
                  <Badge tone="error">{{ g.objects_exhausted }} 已放弃</Badge>
                </span>
              </div>
            </td>
            <td class="px-2 py-2.5 text-[11.5px] tabular-nums">{{ g.retry_count }}</td>
            <td class="px-2 py-2.5 font-mono text-[11.5px] text-muted-foreground">
              <RouterLink
                v-if="g.leased_by"
                :to="`/workers?id=${encodeURIComponent(g.leased_by)}`"
                class="transition hover:text-primary"
                title="跳转到该 worker 卡片"
              >
                {{ g.leased_by }}
              </RouterLink>
              <template v-else>—</template>
            </td>
            <td class="px-2 py-2.5 text-[11.5px] text-muted-foreground">{{ fmtAge(g.updated_at) }}</td>
            <td class="max-w-[320px] px-2 py-2.5 font-mono text-[11.5px] text-danger">
              <ErrorCell :error="g.error" />
            </td>
            <td class="space-x-1 whitespace-nowrap px-5 py-2.5 text-right">
              <Button
                v-if="cancellable.has(g.state)"
                variant="destructive"
                size="sm"
                :pending="cancellingId === g.granule_id"
                pending-label="取消"
                @click="emit('cancel', g)"
              >
                取消
              </Button>
              <Button
                v-if="retryable.has(g.state)"
                size="sm"
                :pending="retryingId === g.granule_id"
                pending-label="重试"
                @click="emit('retry', g.granule_id)"
              >
                重试
              </Button>
            </td>
          </tr>
          <tr v-if="expanded === g.granule_id" class="bg-muted/40">
            <td colspan="7" class="space-y-3 px-5 py-3">
              <StageTimingStrip :granule-id="g.granule_id" />
              <ProgressTimeline :granule-id="g.granule_id" />
              <GranuleEvents :granule-id="g.granule_id" :batch-id="batchId" />
            </td>
          </tr>
        </template>
        <tr v-if="rows.length === 0">
          <td colspan="7"><EmptyState title="该筛选条件下没有数据粒" /></td>
        </tr>
      </tbody>
    </table>
  </div>
</template>
