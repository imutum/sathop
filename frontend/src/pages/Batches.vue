<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useQuery } from "@tanstack/vue-query";
import { useRoute, useRouter } from "vue-router";
import { API, type BatchSummary } from "@/api";
import { fmtAge } from "@/i18n";
import { requestConfirm } from "@/composables/useConfirm";
import { K } from "@/queryKeys";
import { useBatchListMutations } from "@/features/batch/useBatchMutations";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { DropdownMenuItem, DropdownMenuSeparator } from "@/components/ui/dropdown-menu";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import CopyButton from "@/components/CopyButton.vue";
import EmptyState from "@/components/EmptyState.vue";
import PageHeader from "@/components/PageHeader.vue";
import BatchProgressCell from "@/features/batch/components/BatchProgressCell.vue";
import QueryState from "@/components/QueryState.vue";
import RowActions from "@/components/RowActions.vue";
import Segmented from "@/components/Segmented.vue";
import TextInput from "@/ui/TextInput.vue";
import CreateBatchModal from "@/features/batch/components/CreateBatchModal.vue";
import { batchProgress, inFlightTotal, isBatchClosed, totalCount } from "@/features/batch/summary";
import { Icon } from "@/components/Icon";

const route = useRoute();
const router = useRouter();
const { retry, cancel, remove, setPaused, invalidate: invalidateBatches } = useBatchListMutations();

const initialBundle = (route.query.bundle as string | undefined) ?? null;
const showCreate = ref(!!initialBundle);
const pendingBundle = ref<string | null>(initialBundle);

if (initialBundle) {
  const next = { ...route.query };
  delete next.bundle;
  router.replace({ query: next });
}

const search = ref((route.query.q as string | undefined) ?? "");
const scope = ref<"active" | "all">(route.query.scope === "all" ? "all" : "active");

watch([search, scope], ([s, sc]) => {
  const next: Record<string, string> = { ...(route.query as Record<string, string>) };
  if (s) next.q = s;
  else delete next.q;
  if (sc === "all") next.scope = "all";
  else delete next.scope;
  router.replace({ query: next });
});

const batches = useQuery({ queryKey: [...K.batches], queryFn: API.batches });
const all = computed(() => batches.data.value ?? []);
const needle = computed(() => search.value.trim().toLowerCase());

function matchesSearch(b: BatchSummary) {
  if (!needle.value) return true;
  return `${b.name} ${b.batch_id} ${b.bundle_ref}`.toLowerCase().includes(needle.value);
}

function toBatchListRow(batch: BatchSummary) {
  return {
    batch,
    ...batchProgress(batch),
    closed: isBatchClosed(batch),
    bundleLink: bundleLink(batch.bundle_ref),
  };
}

const visible = computed(() =>
  all.value
    .filter((b) => {
      if (scope.value === "active" && isBatchClosed(b)) return false;
      return matchesSearch(b);
    })
    .map(toBatchListRow),
);

const allCount = computed(() => all.value.length);
const activeCount = computed(() => all.value.filter((b) => !isBatchClosed(b)).length);


function bundleLink(ref: string): { name: string; version: string } | null {
  if (!ref.startsWith("orch:")) return null;
  const [name, version = ""] = ref.slice(5).split("@");
  return { name, version };
}

async function confirmCancel(b: BatchSummary) {
  const ok = await requestConfirm({
    title: `取消批次 "${b.name}"？`,
    description: `将取消尚未完成的 ${inFlightTotal(b)} 条数据粒。\n\n待交付、待清理及已完成的数据粒不受影响。`,
    confirmText: "取消批次",
    tone: "danger",
  });
  if (ok) cancel.mutate(b.batch_id);
}

async function confirmDelete(b: BatchSummary) {
  const t = totalCount(b.counts);
  const ok = await requestConfirm({
    title: `永久删除批次 "${b.name}"？`,
    description:
      t === 0
        ? "将清除该批次的运行记录。已确认的交付台账继续保留。此操作不可恢复。"
        : `将删除 ${t} 条数据粒，并清除运行记录。已确认的交付台账继续保留。\n` +
          `已上传的产物文件不会删除。此操作不可恢复。`,
    confirmText: "永久删除",
    tone: "danger",
    // 空批（无任何数据粒）跳过名称二次输入 —— 没东西可以丢失。
    ...(t > 0 ? { requireText: b.name, inputLabel: `请输入批次名称 "${b.name}" 确认` } : {}),
  });
  if (ok) remove.mutate({ id: b.batch_id, force: false });
}

function closeCreate() {
  showCreate.value = false;
  pendingBundle.value = null;
}

function onCreated() {
  closeCreate();
  invalidateBatches();
}
</script>

<template>
  <div class="space-y-6">
    <PageHeader
      title="批次"
      description="管理数据处理批次，跟踪执行与交付进度"
    >
      <template #actions>
        <Button variant="default" @click="showCreate = true" title="提交一组数据粒，绑定任务包与凭证">
          <Icon name="plus" :size="13" />
          新建批次
        </Button>
      </template>
    </PageHeader>

    <div class="flex flex-wrap items-center justify-between gap-3">
      <div class="flex items-center gap-2">
        <div class="w-72">
          <TextInput
            v-model="search"
            placeholder="搜索：名称 / ID / 任务包"
            aria-label="搜索批次"
          >
            <template #leftIcon>
              <Icon name="search" :size="13" />
            </template>
          </TextInput>
        </div>
        <Segmented
          v-model="scope"
          :options="[
            { value: 'active', label: '未完成', count: activeCount },
            { value: 'all', label: '全部', count: allCount },
          ]"
        />
      </div>
      <Badge variant="info" class="h-7 tabular-nums">
        <span class="text-foreground">{{ visible.length }}</span>
        <span class="text-muted-foreground/80">/ {{ allCount }}</span>
      </Badge>
    </div>

    <CreateBatchModal
      v-if="showCreate"
      :initial-bundle="pendingBundle ?? undefined"
      @close="closeCreate"
      @created="onCreated"
    />

    <Card>
      <QueryState :query="batches">
        <template #loading>
          <div class="space-y-2 p-5">
            <Skeleton v-for="n in 5" :key="n" class="h-14 w-full" />
          </div>
        </template>
        <template #error="{ error, retry: retryFetch }">
          <div class="p-5">
            <Alert variant="destructive">
              <AlertDescription class="flex items-center justify-between gap-3">
                <span>加载批次失败：{{ error.message }}</span>
                <Button size="sm" variant="outline" @click="retryFetch">重试</Button>
              </AlertDescription>
            </Alert>
          </div>
        </template>
        <template #empty>
          <EmptyState
            title="暂无批次"
            description="选择任务包并添加数据，创建首个批次。"
            illustration="inbox"
          >
            <template #action>
              <Button variant="default" @click="showCreate = true">
                <Icon name="plus" :size="13" />
                新建批次
              </Button>
            </template>
          </EmptyState>
        </template>
        <template #default>
          <EmptyState
            v-if="visible.length === 0"
            title="没有符合条件的批次"
          />
          <template v-else>
          <!-- Narrow: card list. min-w-[820px] table needs lg+ to feel right. -->
          <ul class="divide-y divide-border/60 lg:hidden">
            <li v-for="row in visible" :key="row.batch.batch_id" class="space-y-3 p-4">
              <div class="flex items-start justify-between gap-3">
                <RouterLink :to="`/batches/${row.batch.batch_id}`" class="min-w-0 flex-1">
                  <div class="truncate font-medium text-foreground transition-colors hover:text-primary">
                    {{ row.batch.name }}
                  </div>
                  <div class="mt-0.5 inline-flex items-center font-mono text-2xs text-muted-foreground">
                    {{ row.batch.batch_id }}
                    <CopyButton :value="row.batch.batch_id" title="复制批次 ID" />
                  </div>
                </RouterLink>
                <div class="flex shrink-0 items-center gap-1.5">
                  <Badge v-if="row.batch.status === 'paused'" tone="warn">已暂停</Badge>
                  <Badge tone="info">{{ row.batch.target_receiver_id ?? "自动分配" }}</Badge>
                </div>
              </div>
              <RouterLink
                v-if="row.bundleLink"
                :to="{
                  path: '/bundles',
                  query: { name: row.bundleLink.name, version: row.bundleLink.version },
                }"
                class="block truncate font-mono text-2xs text-muted-foreground transition-colors hover:text-primary"
                title="在任务包页查看"
              >
                {{ row.batch.bundle_ref }}
              </RouterLink>
              <div v-else class="truncate font-mono text-2xs text-muted-foreground">
                {{ row.batch.bundle_ref }}
              </div>
              <BatchProgressCell
                :done="row.done"
                :total="row.total"
                :pct="row.pct"
                :eta-realtime="row.batch.status === 'paused' ? null : row.batch.eta_realtime ?? null"
                :in-flight="row.inFlight"
                :errors="row.errors"
                :exhausted="row.batch.objects_exhausted"
              />
              <div class="flex flex-wrap items-center justify-between gap-2">
                <span class="text-2xs text-muted-foreground">{{ fmtAge(row.batch.created_at) }}</span>
                <RowActions>
                  <template #primary>
                    <Button
                      v-if="(row.batch.counts.failed ?? 0) > 0"
                      size="sm"
                      :pending="retry.isPending.value && retry.variables.value === row.batch.batch_id"
                      pending-label="重试中…"
                      @click="retry.mutate(row.batch.batch_id)"
                    >
                      重试失败 ({{ row.batch.counts.failed }})
                    </Button>
                    <Button
                      v-if="row.inFlight > 0"
                      variant="destructive"
                      size="sm"
                      :pending="cancel.isPending.value && cancel.variables.value === row.batch.batch_id"
                      pending-label="取消中…"
                      @click="confirmCancel(row.batch)"
                    >
                      取消 ({{ row.inFlight }})
                    </Button>
                  </template>
                  <DropdownMenuItem
                    v-if="row.batch.status === 'paused' || !row.closed"
                    :disabled="setPaused.isPending.value && setPaused.variables.value?.id === row.batch.batch_id"
                    @select="setPaused.mutate({ id: row.batch.batch_id, paused: row.batch.status !== 'paused' })"
                  >
                    {{ row.batch.status === "paused" ? "恢复调度" : "暂停调度" }}
                  </DropdownMenuItem>
                  <DropdownMenuSeparator />
                  <DropdownMenuItem
                    class="text-danger focus:bg-danger/10 focus:text-danger"
                    @select="confirmDelete(row.batch)"
                  >
                    永久删除…
                  </DropdownMenuItem>
                </RowActions>
              </div>
            </li>
          </ul>
          <!-- lg+ : original table. -->
          <div class="hidden lg:block">
            <Table class="min-w-[820px]">
              <TableHeader class="bg-muted/50">
                <TableRow>
                  <TableHead class="px-5">批次</TableHead>
                  <TableHead>任务包</TableHead>
                  <TableHead>目标接收端</TableHead>
                  <TableHead>进度</TableHead>
                  <TableHead>创建时间</TableHead>
                  <TableHead class="px-5 text-right">操作</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                <TableRow v-for="row in visible" :key="row.batch.batch_id">
                  <TableCell class="px-5 py-3.5">
                    <RouterLink :to="`/batches/${row.batch.batch_id}`" class="block">
                      <div class="flex items-center gap-2">
                        <span class="font-medium text-foreground transition-colors hover:text-primary">{{ row.batch.name }}</span>
                        <Badge v-if="row.batch.status === 'paused'" tone="warn">已暂停</Badge>
                      </div>
                      <div class="mt-0.5 inline-flex items-center font-mono text-2xs text-muted-foreground">
                        {{ row.batch.batch_id }}
                        <CopyButton :value="row.batch.batch_id" title="复制批次 ID" />
                      </div>
                    </RouterLink>
                  </TableCell>
                  <TableCell class="py-3.5 font-mono text-cell text-muted-foreground">
                    <RouterLink
                      v-if="row.bundleLink"
                      :to="{
                        path: '/bundles',
                        query: { name: row.bundleLink.name, version: row.bundleLink.version },
                      }"
                      class="transition-colors hover:text-primary"
                      title="在任务包页查看"
                    >
                      {{ row.batch.bundle_ref }}
                    </RouterLink>
                    <template v-else>{{ row.batch.bundle_ref }}</template>
                  </TableCell>
                  <TableCell class="py-3.5">
                    <Badge tone="info">{{ row.batch.target_receiver_id ?? "自动分配" }}</Badge>
                  </TableCell>
                  <TableCell class="w-[280px] py-3.5">
                    <BatchProgressCell
                      :done="row.done"
                      :total="row.total"
                      :pct="row.pct"
                        :eta-realtime="row.batch.status === 'paused' ? null : row.batch.eta_realtime ?? null"
                      :in-flight="row.inFlight"
                      :errors="row.errors"
                      :exhausted="row.batch.objects_exhausted"
                    />
                  </TableCell>
                  <TableCell class="py-3.5 text-cell text-muted-foreground">{{ fmtAge(row.batch.created_at) }}</TableCell>
                  <TableCell class="whitespace-nowrap px-5 py-3.5 text-right">
                    <RowActions align="end">
                      <template #primary>
                        <Button
                          v-if="(row.batch.counts.failed ?? 0) > 0"
                          size="sm"
                          :pending="retry.isPending.value && retry.variables.value === row.batch.batch_id"
                          pending-label="重试中…"
                          @click="retry.mutate(row.batch.batch_id)"
                        >
                          重试失败 ({{ row.batch.counts.failed }})
                        </Button>
                        <Button
                          v-if="row.inFlight > 0"
                          variant="destructive"
                          size="sm"
                          :pending="cancel.isPending.value && cancel.variables.value === row.batch.batch_id"
                          pending-label="取消中…"
                          @click="confirmCancel(row.batch)"
                        >
                          取消 ({{ row.inFlight }})
                        </Button>
                      </template>
                      <DropdownMenuItem
                        v-if="row.batch.status === 'paused' || !row.closed"
                        :disabled="setPaused.isPending.value && setPaused.variables.value?.id === row.batch.batch_id"
                        @select="setPaused.mutate({ id: row.batch.batch_id, paused: row.batch.status !== 'paused' })"
                      >
                        {{ row.batch.status === "paused" ? "恢复调度" : "暂停调度" }}
                      </DropdownMenuItem>
                      <DropdownMenuSeparator />
                      <DropdownMenuItem
                        class="text-danger focus:bg-danger/10 focus:text-danger"
                        @select="confirmDelete(row.batch)"
                      >
                        永久删除…
                      </DropdownMenuItem>
                    </RowActions>
                  </TableCell>
                </TableRow>
              </TableBody>
            </Table>
          </div>
          </template>
        </template>
      </QueryState>
    </Card>
  </div>
</template>
