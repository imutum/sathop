<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useMutation, useQuery, useQueryClient } from "@tanstack/vue-query";
import { useRoute } from "vue-router";
import { API, type BundleDetail, type BundleSummary } from "../api";
import { fmtBytes } from "../ui/format";
import { fmtAge } from "../i18n";
import { useToast } from "../composables/useToast";
import ActionButton from "../ui/ActionButton.vue";
import Badge from "../ui/Badge.vue";
import Card from "../ui/Card.vue";
import EmptyState from "../ui/EmptyState.vue";
import PageHeader from "../ui/PageHeader.vue";
import BundleManifestView from "./BundleManifestView.vue";
import UploadBundleModal from "./UploadBundleModal.vue";
import { Icon } from "../ui/Icon";

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

const rows = computed(() => list.data.value ?? []);

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
      title="任务包"
      description="用户脚本注册表 · 批次通过 orch:<name>@<version> 引用"
    >
      <template #actions>
        <ActionButton tone="primary" @click="showUpload = true">
          <Icon name="upload" :size="13" />
          上传 ZIP
        </ActionButton>
      </template>
    </PageHeader>

    <div class="grid gap-6 lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
      <Card :padded="false">
        <EmptyState
          v-if="rows.length === 0"
          title="还没有任务包"
          description='点击上方"上传 ZIP"开始添加。'
        >
          <template #icon>
            <Icon name="bundles" :size="20" />
          </template>
        </EmptyState>
        <div v-else class="overflow-x-auto">
          <table class="w-full text-sm">
            <thead class="bg-subtle/50 th-row">
              <tr>
                <th class="px-5 py-3">名称</th>
                <th class="px-2 py-3">版本</th>
                <th class="px-2 py-3">大小</th>
                <th class="px-2 py-3" title="引用此包的批次数">引用</th>
                <th class="px-5 py-3">上传</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="b in rows"
                :key="`${b.name}@${b.version}`"
                @click="selected = { name: b.name, version: b.version }"
                :class="[
                  'cursor-pointer border-t border-border/60 transition',
                  isActive(b) ? 'bg-accent-soft/60' : 'hover:bg-subtle/50',
                ]"
              >
                <td class="px-5 py-2.5 font-mono text-[12px] font-medium">{{ b.name }}</td>
                <td class="px-2 py-2.5">
                  <Badge tone="info">{{ b.version }}</Badge>
                </td>
                <td class="px-2 py-2.5 text-[11.5px] text-muted tabular-nums">{{ fmtBytes(b.size) }}</td>
                <td class="px-2 py-2.5 text-[11.5px] tabular-nums">
                  <span v-if="b.in_use_count > 0" class="font-medium text-text">
                    {{ b.in_use_count }}
                  </span>
                  <span v-else class="text-muted/60">0</span>
                </td>
                <td class="px-5 py-2.5 text-[11.5px] text-muted">{{ fmtAge(b.uploaded_at) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </Card>

      <Card>
        <EmptyState
          v-if="!selected"
          title="未选择任务包"
          description="选择左侧任意任务包查看清单 / 文件浏览。"
        >
          <template #icon>
            <Icon name="bundles" :size="20" />
          </template>
        </EmptyState>
        <div v-else-if="detail.isLoading.value" class="py-8 text-center text-sm text-muted">
          加载中…
        </div>
        <BundleManifestView
          v-else-if="detail.data.value"
          :d="detail.data.value"
          :pending="del.isPending.value"
          :error="del.error.value?.message ?? null"
          @delete="del.mutate(selected!)"
        />
      </Card>
    </div>

    <UploadBundleModal
      v-if="showUpload"
      @close="showUpload = false"
      @uploaded="onUploaded"
    />
  </div>
</template>
