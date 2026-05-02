<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useMutation, useQuery, useQueryClient } from "@tanstack/vue-query";
import { useRoute } from "vue-router";
import { API, type BundleDetail, type BundleSummary } from "@/api";
import { fmtBytes } from "@/lib/format";
import { fmtAge } from "@/i18n";
import { useToast } from "@/composables/useToast";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import EmptyState from "@/components/EmptyState.vue";
import PageHeader from "@/components/PageHeader.vue";
import QueryState from "@/components/QueryState.vue";
import { Skeleton } from "@/components/ui/skeleton";
import { Alert, AlertDescription } from "@/components/ui/alert";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import BundleManifestView from "@/features/bundle/components/BundleManifestView.vue";
import UploadBundleModal from "@/features/bundle/components/UploadBundleModal.vue";
import { Icon } from "@/components/Icon";

const qc = useQueryClient();
const toast = useToast();
const route = useRoute();

const initial = (() => {
  const n = route.query.name as string | undefined;
  const v = route.query.version as string | undefined;
  return n && v ? { name: n, version: v } : null;
})();

const selected = ref<{ name: string; version: string } | null>(initial);
const showUpload = ref(false);

watch(
  () => [route.query.name, route.query.version] as const,
  ([n, v]) => {
    if (n && v && (selected.value?.name !== n || selected.value?.version !== v)) {
      selected.value = { name: n as string, version: v as string };
    }
  },
);

const list = useQuery({ queryKey: ["bundles"], queryFn: API.bundles });
const detail = useQuery({
  queryKey: computed(() => ["bundle-detail", selected.value?.name, selected.value?.version]),
  queryFn: () => API.bundleDetail(selected.value!.name, selected.value!.version),
  enabled: computed(() => !!selected.value),
});

const del = useMutation({
  mutationFn: (v: { name: string; version: string }) => API.deleteBundle(v.name, v.version),
  onSuccess: (_r, v) => {
    qc.invalidateQueries({ queryKey: ["bundles"] });
    selected.value = null;
    toast.success(`已删除任务包 ${v.name}@${v.version}`);
  },
  onError: (e: Error) => toast.error(`删除失败：${e.message}`),
});

function isActive(b: BundleSummary) {
  return selected.value?.name === b.name && selected.value?.version === b.version;
}

function onUploaded(d: BundleDetail) {
  qc.invalidateQueries({ queryKey: ["bundles"] });
  selected.value = { name: d.name, version: d.version };
  showUpload.value = false;
}
</script>

<template>
  <div class="space-y-6">
    <PageHeader
      n="03"
      kicker="PAYLOAD · BUNDLES"
      title="任务包"
      description="用户脚本注册表 · 批次通过 orch:<name>@<version> 引用"
    >
      <template #actions>
        <Button variant="default" @click="showUpload = true">
          <Icon name="upload" :size="13" />
          上传 ZIP
        </Button>
      </template>
    </PageHeader>

    <div class="grid gap-6 lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
      <Card>
        <QueryState :query="list">
          <template #loading>
            <div class="space-y-2 p-5">
              <Skeleton v-for="n in 5" :key="n" class="h-10 w-full" />
            </div>
          </template>
          <template #error="{ error, retry }">
            <div class="p-5">
              <Alert variant="destructive">
                <AlertDescription class="flex items-center justify-between gap-3">
                  <span>加载失败：{{ error.message }}</span>
                  <Button size="sm" variant="outline" @click="retry">重试</Button>
                </AlertDescription>
              </Alert>
            </div>
          </template>
          <template #empty>
            <EmptyState
              title="还没有任务包"
              description='点击上方"上传 ZIP"开始添加。'
              illustration="inbox"
            />
          </template>
          <template #default="{ data: bundleRows }">
            <!-- Narrow: card list. Each row collapses into a stacked card. -->
            <ul class="divide-y divide-border/60 sm:hidden">
              <li
                v-for="b in bundleRows"
                :key="`${b.name}@${b.version}`"
                @click="selected = { name: b.name, version: b.version }"
                :class="[
                  'cursor-pointer p-4 transition',
                  isActive(b) ? 'bg-accent/60' : 'hover:bg-muted/50',
                ]"
              >
                <div class="flex items-start justify-between gap-3">
                  <div class="min-w-0 flex-1 truncate font-mono text-[12px] font-medium">{{ b.name }}</div>
                  <Badge tone="info">{{ b.version }}</Badge>
                </div>
                <div class="mt-2 flex items-center justify-between text-2xs text-muted-foreground">
                  <span class="tabular-nums">{{ fmtBytes(b.size) }}</span>
                  <span class="tabular-nums">
                    <span v-if="b.in_use_count > 0" class="font-medium text-foreground">{{ b.in_use_count }}</span>
                    <span v-else class="text-muted-foreground/60">0</span>
                    <span class="ml-0.5">引用</span>
                  </span>
                  <span>{{ fmtAge(b.uploaded_at) }}</span>
                </div>
              </li>
            </ul>
            <!-- sm+ : table. -->
            <div class="hidden sm:block">
            <Table>
              <TableHeader class="bg-muted/50">
                <TableRow>
                  <TableHead class="px-5">名称</TableHead>
                  <TableHead>版本</TableHead>
                  <TableHead>大小</TableHead>
                  <TableHead title="引用此包的批次数">引用</TableHead>
                  <TableHead class="px-5">上传</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                <TableRow
                  v-for="b in bundleRows"
                  :key="`${b.name}@${b.version}`"
                  @click="selected = { name: b.name, version: b.version }"
                  :class="['cursor-pointer', isActive(b) ? 'bg-accent/60' : '']"
                >
                  <TableCell class="px-5 font-mono text-[12px] font-medium">{{ b.name }}</TableCell>
                  <TableCell>
                    <Badge tone="info">{{ b.version }}</Badge>
                  </TableCell>
                  <TableCell class="text-cell text-muted-foreground tabular-nums">{{ fmtBytes(b.size) }}</TableCell>
                  <TableCell class="text-cell tabular-nums">
                    <span v-if="b.in_use_count > 0" class="font-medium text-foreground">
                      {{ b.in_use_count }}
                    </span>
                    <span v-else class="text-muted-foreground/60">0</span>
                  </TableCell>
                  <TableCell class="px-5 text-cell text-muted-foreground">{{ fmtAge(b.uploaded_at) }}</TableCell>
                </TableRow>
              </TableBody>
            </Table>
            </div>
          </template>
        </QueryState>
      </Card>

      <Card>
        <CardContent class="pt-6">
          <EmptyState
            v-if="!selected"
            title="未选择任务包"
            description="选择左侧任意任务包查看清单 / 文件浏览。"
            illustration="inbox"
          />
          <div v-else-if="detail.isLoading.value" class="py-8 text-center text-sm text-muted-foreground">
            加载中…
          </div>
          <BundleManifestView
            v-else-if="detail.data.value"
            :d="detail.data.value"
            :pending="del.isPending.value"
            :error="del.error.value?.message ?? null"
            @delete="del.mutate(selected!)"
          />
        </CardContent>
      </Card>
    </div>

    <UploadBundleModal
      v-if="showUpload"
      @close="showUpload = false"
      @uploaded="onUploaded"
    />
  </div>
</template>
