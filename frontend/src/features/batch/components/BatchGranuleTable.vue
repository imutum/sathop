<script setup lang="ts">
import type { GranuleRow, ProgressRow, GranuleState } from "@/api";
import { fmtAge, stateLabel } from "@/i18n";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import EmptyState from "@/components/EmptyState.vue";
import { Icon } from "@/components/Icon";
import { stripBatchPrefix } from "@/lib/utils";
import ErrorCell from "@/features/batch/components/ErrorCell.vue";
import GranuleExpandedDetail from "@/features/batch/components/GranuleExpandedDetail.vue";
import LatestProgressLine from "@/features/batch/components/LatestProgressLine.vue";

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
          'space-y-3 p-4 transition-colors',
          g.granule_id === highlight ? 'bg-accent/40' : '',
        ]"
      >
        <div class="flex items-start justify-between gap-3">
          <div class="min-w-0 flex-1">
            <button
              type="button"
              @click="emit('toggle', g.granule_id)"
              class="mr-1 inline-flex h-5 w-5 items-center justify-center rounded text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
              :aria-expanded="expanded === g.granule_id"
              :title="expanded === g.granule_id ? '收起进度' : '展开进度'"
            >
              <Icon
                :name="expanded === g.granule_id ? 'chevronDown' : 'chevronRight'"
                :size="12"
                :stroke-width="2.2"
              />
            </button>
            <span class="break-all font-mono text-cell">{{ stripBatchPrefix(g.granule_id, props.batchId) }}</span>
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
        <div class="flex flex-wrap items-center gap-x-4 gap-y-1 text-2xs text-muted-foreground">
          <span class="font-mono">
            领取方:
            <RouterLink
              v-if="g.leased_by"
              :to="`/workers?id=${encodeURIComponent(g.leased_by)}`"
              class="transition-colors hover:text-primary"
              title="跳转到该 worker 卡片"
            >
              {{ g.leased_by }}
            </RouterLink>
            <template v-else>—</template>
          </span>
          <span>{{ fmtAge(g.updated_at) }}</span>
        </div>
        <div
          v-if="g.error || g.stdout_tail || g.stderr_tail"
          class="font-mono text-cell text-danger"
        >
          <ErrorCell
            :error="g.error"
            :stdout-tail="g.stdout_tail"
            :stderr-tail="g.stderr_tail"
            :retry-count="g.retry_count"
          />
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
        <GranuleExpandedDetail
          v-if="expanded === g.granule_id"
          :granule-id="g.granule_id"
          :batch-id="batchId"
          class="rounded-md bg-muted/40 p-3"
        />
      </li>
    </template>
  </ul>

  <!-- lg+ : table. Fault-first column order — 状态(含展开把手) + 错误 lead the
       scan; 数据粒 ID demoted to a secondary mono column. 重试 folded into 错误. -->
  <div class="hidden lg:block">
    <Table>
      <TableHeader class="bg-muted/50">
        <TableRow>
          <TableHead class="px-5">状态</TableHead>
          <TableHead>错误</TableHead>
          <TableHead>领取方</TableHead>
          <TableHead>更新</TableHead>
          <TableHead>数据粒</TableHead>
          <TableHead class="px-5 text-right">操作</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        <template v-for="g in rows" :key="g.granule_id">
          <TableRow
            :ref="(el) => emit('rowRef', g.granule_id, el as Element | null)"
            :class="['align-top', g.granule_id === highlight ? 'bg-accent/40' : '']"
          >
            <TableCell class="px-5 py-2.5">
              <div class="flex items-start gap-1">
                <button
                  type="button"
                  @click="emit('toggle', g.granule_id)"
                  class="mt-0.5 inline-flex h-5 w-5 shrink-0 items-center justify-center rounded text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
                  :aria-expanded="expanded === g.granule_id"
                  :title="expanded === g.granule_id ? '收起进度' : '展开进度'"
                >
                  <Icon
                    :name="expanded === g.granule_id ? 'chevronDown' : 'chevronRight'"
                    :size="12"
                    :stroke-width="2.2"
                  />
                </button>
                <div class="min-w-0">
                  <div class="flex flex-wrap items-center gap-1">
                    <Badge :tone="g.state" dot>{{ stateLabel(g.state) }}</Badge>
                    <span
                      v-if="g.objects_exhausted > 0"
                      :title="`${g.objects_exhausted} 个产物超出 receiver 拉取重试上限，已停止派发`"
                    >
                      <Badge tone="error">{{ g.objects_exhausted }} 已放弃</Badge>
                    </span>
                  </div>
                  <LatestProgressLine
                    v-if="latestProgress[g.granule_id]"
                    :row="latestProgress[g.granule_id]"
                  />
                </div>
              </div>
            </TableCell>
            <TableCell class="max-w-[340px] py-2.5 font-mono text-cell text-danger">
              <ErrorCell
                :error="g.error"
                :stdout-tail="g.stdout_tail"
                :stderr-tail="g.stderr_tail"
                :retry-count="g.retry_count"
              />
            </TableCell>
            <TableCell class="py-2.5 font-mono text-cell text-muted-foreground">
              <RouterLink
                v-if="g.leased_by"
                :to="`/workers?id=${encodeURIComponent(g.leased_by)}`"
                class="transition-colors hover:text-primary"
                title="跳转到该 worker 卡片"
              >
                {{ g.leased_by }}
              </RouterLink>
              <template v-else>—</template>
            </TableCell>
            <TableCell class="py-2.5 text-cell text-muted-foreground">{{ fmtAge(g.updated_at) }}</TableCell>
            <TableCell class="py-2.5 font-mono text-cell text-muted-foreground">
              {{ stripBatchPrefix(g.granule_id, props.batchId) }}
            </TableCell>
            <TableCell class="space-x-1 whitespace-nowrap px-5 py-2.5 text-right">
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
            </TableCell>
          </TableRow>
          <TableRow v-if="expanded === g.granule_id" class="bg-muted/40">
            <TableCell colspan="6" class="px-5 py-3">
              <GranuleExpandedDetail :granule-id="g.granule_id" :batch-id="batchId" />
            </TableCell>
          </TableRow>
        </template>
        <TableRow v-if="rows.length === 0">
          <TableCell colspan="6"><EmptyState title="该筛选条件下没有数据粒" /></TableCell>
        </TableRow>
      </TableBody>
    </Table>
  </div>
</template>
