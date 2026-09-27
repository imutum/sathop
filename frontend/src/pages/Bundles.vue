<script setup lang="ts">
import { computed, nextTick, ref, watch } from "vue";
import { useMutation, useQuery, useQueryClient } from "@tanstack/vue-query";
import { useRoute } from "vue-router";
import { API, type BundleDetail } from "@/api";
import { K } from "@/queryKeys";
import { useToast } from "@/composables/useToast";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import EmptyState from "@/components/EmptyState.vue";
import PageHeader from "@/components/PageHeader.vue";
import QueryState from "@/components/QueryState.vue";
import { Skeleton } from "@/components/ui/skeleton";
import { Alert, AlertDescription } from "@/components/ui/alert";
import BundleCatalog from "@/features/bundle/components/BundleCatalog.vue";
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
const detailPanel = ref<HTMLElement | null>(null);
const listPanel = ref<HTMLElement | null>(null);

watch(
  () => [route.query.name, route.query.version] as const,
  ([n, v]) => {
    if (n && v && (selected.value?.name !== n || selected.value?.version !== v)) {
      selected.value = { name: n as string, version: v as string };
    }
  },
);

const list = useQuery({ queryKey: [...K.bundles], queryFn: API.bundles });
const detail = useQuery({
  queryKey: computed(() => [...K.bundleDetail, selected.value?.name, selected.value?.version]),
  queryFn: () => API.bundleDetail(selected.value!.name, selected.value!.version),
  enabled: computed(() => !!selected.value),
});

const del = useMutation({
  mutationFn: (v: { name: string; version: string }) => API.deleteBundle(v.name, v.version),
  onSuccess: (_r, v) => {
    qc.invalidateQueries({ queryKey: [...K.bundles] });
    selected.value = null;
    toast.success(`已删除任务包 ${v.name}@${v.version}`);
  },
  onError: (e: Error) => toast.error(`删除失败：${e.message}`),
});

async function selectBundle(bundle: { name: string; version: string }) {
  selected.value = { name: bundle.name, version: bundle.version };
  await nextTick();
  detailPanel.value?.focus({ preventScroll: true });
}

async function backToList() {
  selected.value = null;
  await nextTick();
  listPanel.value?.focus({ preventScroll: true });
}

function onUploaded(d: BundleDetail) {
  qc.invalidateQueries({ queryKey: [...K.bundles] });
  selected.value = { name: d.name, version: d.version };
  showUpload.value = false;
}
</script>

<template>
  <div class="space-y-6">
    <PageHeader
      title="任务包"
      description="管理处理脚本及版本，供批次执行使用"
    >
      <template #actions>
        <Button variant="default" @click="showUpload = true" title="上传含 manifest.yaml + 入口脚本的 ZIP 包">
          <Icon name="upload" :size="13" />
          上传 ZIP
        </Button>
      </template>
    </PageHeader>

    <div class="grid items-start gap-5 xl:grid-cols-[340px_minmax(0,1fr)] 2xl:grid-cols-[380px_minmax(0,1fr)]">
      <Card :class="['min-w-0 overflow-hidden xl:sticky xl:top-6', selected ? 'hidden xl:block' : '']">
        <div ref="listPanel" tabindex="-1" aria-label="任务包目录" class="outline-none">
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
                title="暂无任务包"
                illustration="inbox"
              >
                <template #description>
                  <div class="space-y-2 text-left">
                    <p>将处理脚本打包为 ZIP 上传，批次通过 <code class="rounded bg-muted px-1 py-0.5 font-mono text-mini">orch:&lt;name&gt;@&lt;version&gt;</code> 引用。</p>
                    <p>ZIP 结构示例：</p>
                    <pre class="rounded bg-muted px-3 py-2 text-mini font-mono text-foreground/80">my-bundle/
  ├── manifest.yaml      # 版本、入口、依赖、输入/输出
  ├── entrypoint.py      # 处理脚本
  └── requirements.txt   # 可选 pip 依赖</pre>
                    <p>本地用 <code class="rounded bg-muted px-1 py-0.5 font-mono text-mini">sathop-upload-bundle</code> 命令上传并校验任务包配置。</p>
                  </div>
                </template>
              </EmptyState>
            </template>
            <template #default="{ data: bundleRows }">
              <BundleCatalog :bundles="bundleRows" :selected="selected" @select="selectBundle" />
            </template>
          </QueryState>
        </div>
      </Card>

      <Card :class="['min-w-0', !selected ? 'hidden xl:block' : '']">
        <CardContent class="pt-6">
          <div ref="detailPanel" tabindex="-1" role="region" aria-label="任务包详情" class="outline-none">
            <Button v-if="selected" variant="ghost" size="sm" class="mb-4 -ml-2 xl:hidden" @click="backToList">
              <Icon name="chevronLeft" :size="14" />返回任务包目录
            </Button>
            <EmptyState
              v-if="!selected"
              title="未选择任务包"
              description="选择任务包，查看配置与文件。"
              illustration="inbox"
            />
            <div v-else-if="detail.isLoading.value" class="py-8 text-center text-sm text-muted-foreground">
              加载中…
            </div>
            <Alert v-else-if="detail.isError.value" variant="destructive">
              <AlertDescription class="flex flex-wrap items-center justify-between gap-3">
                <span>任务包加载失败：{{ detail.error.value?.message }}</span>
                <Button variant="outline" size="sm" @click="detail.refetch()">重试</Button>
              </AlertDescription>
            </Alert>
            <BundleManifestView
              v-else-if="detail.data.value"
              :key="`${detail.data.value.name}@${detail.data.value.version}`"
              :d="detail.data.value"
              :pending="del.isPending.value"
              :error="del.error.value?.message ?? null"
              @delete="del.mutate(selected!)"
            />
          </div>
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
