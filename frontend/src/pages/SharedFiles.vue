<script setup lang="ts">
import { ref } from "vue";
import { useMutation, useQuery, useQueryClient } from "@tanstack/vue-query";
import { API, type SharedFileInfo } from "@/api";
import { fmtBytes } from "@/lib/format";
import { fmtAge } from "@/i18n";
import { requestConfirm } from "@/composables/useConfirm";
import { useToast } from "@/composables/useToast";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
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
import QueryState from "@/components/QueryState.vue";
import UploadSharedModal from "@/features/shared/components/UploadSharedModal.vue";
import { Icon } from "@/components/Icon";

const qc = useQueryClient();
const toast = useToast();
const showUpload = ref(false);
const replaceTarget = ref<SharedFileInfo | null>(null);

const list = useQuery({ queryKey: ["shared-files"], queryFn: API.sharedFiles });

const del = useMutation({
  mutationFn: (name: string) => API.deleteSharedFile(name),
  onSuccess: (_r, name) => {
    qc.invalidateQueries({ queryKey: ["shared-files"] });
    toast.success(`已删除 ${name}`);
  },
  onError: (e: Error) => toast.error(`删除失败：${e.message}`),
});

async function confirmDelete(f: SharedFileInfo) {
  const ok = await requestConfirm({
    title: `删除共享文件 ${f.name}？`,
    description: "若仍被某个任务包的 shared_files 引用，服务端会拒绝删除。",
    confirmText: "删除",
    tone: "danger",
  });
  if (ok) del.mutate(f.name);
}

function onUploaded() {
  qc.invalidateQueries({ queryKey: ["shared-files"] });
  showUpload.value = false;
  replaceTarget.value = null;
}
</script>

<template>
  <div class="space-y-6">
    <PageHeader n="04" kicker="PAYLOAD · SHARED" title="共享文件">
      <template #description>
        被任务包通过
        <code class="rounded bg-muted px-1.5 py-0.5 readout text-2xs">shared_files</code>
        引用的辅助资源，Worker 按需拉取到
        <code class="rounded bg-muted px-1.5 py-0.5 readout text-2xs">$SATHOP_SHARED_DIR</code>。
      </template>
      <template #actions>
        <Button variant="default" @click="showUpload = true">
          <Icon name="upload" :size="13" />
          上传文件
        </Button>
      </template>
    </PageHeader>

    <Card>
      <QueryState :query="list">
        <template #loading>
          <div class="space-y-2 p-5">
            <Skeleton v-for="n in 4" :key="n" class="h-10 w-full" />
          </div>
        </template>
        <template #error="{ error, retry }">
          <div class="p-5">
            <Alert variant="destructive">
              <AlertDescription class="flex items-center justify-between gap-3">
                <span>加载共享文件失败：{{ error.message }}</span>
                <Button size="sm" variant="outline" @click="retry">重试</Button>
              </AlertDescription>
            </Alert>
          </div>
        </template>
        <template #empty>
          <EmptyState
            title="还没有共享文件"
            description='点击上方"上传文件"添加第一个。'
            illustration="inbox"
          />
        </template>
        <template #default="{ data: files }">
          <!-- Narrow: card list per file. -->
          <ul class="divide-y divide-border/60 sm:hidden">
            <li v-for="f in files" :key="f.name" class="space-y-2 p-4">
              <div class="font-mono text-[12px] font-medium">{{ f.name }}</div>
              <div class="flex items-center justify-between text-2xs text-muted-foreground">
                <span class="tabular-nums">{{ fmtBytes(f.size) }}</span>
                <span class="tabular-nums">{{ fmtAge(f.uploaded_at) }}</span>
              </div>
              <div class="flex items-center text-2xs">
                <span class="font-mono text-muted-foreground" :title="f.sha256">
                  {{ f.sha256.slice(0, 12) }}…
                </span>
                <CopyButton :value="f.sha256" title="复制完整 SHA256" />
              </div>
              <div v-if="f.description" class="text-2xs text-muted-foreground">{{ f.description }}</div>
              <div class="flex justify-end gap-1.5">
                <Button size="sm" @click="replaceTarget = f">替换</Button>
                <Button
                  variant="destructive"
                  size="sm"
                  :pending="del.isPending.value && del.variables.value === f.name"
                  pending-label="删除中…"
                  @click="confirmDelete(f)"
                >
                  删除
                </Button>
              </div>
            </li>
          </ul>
          <!-- sm+ : table. -->
          <div class="hidden sm:block">
            <Table>
              <TableHeader class="bg-muted/50">
                <TableRow>
                  <TableHead class="px-5">名称</TableHead>
                  <TableHead>大小</TableHead>
                  <TableHead>SHA256</TableHead>
                  <TableHead>描述</TableHead>
                  <TableHead>上传</TableHead>
                  <TableHead class="px-5 text-right">操作</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                <TableRow v-for="f in files" :key="f.name">
                  <TableCell class="px-5 py-3 font-mono text-[12px] font-medium">{{ f.name }}</TableCell>
                  <TableCell class="py-3 text-cell text-muted-foreground tabular-nums">
                    {{ fmtBytes(f.size) }}
                  </TableCell>
                  <TableCell class="py-3 text-cell">
                    <span class="font-mono" :title="f.sha256">{{ f.sha256.slice(0, 12) }}…</span>
                    <CopyButton :value="f.sha256" title="复制完整 SHA256" />
                  </TableCell>
                  <TableCell class="py-3 text-cell text-muted-foreground">
                    <template v-if="f.description">{{ f.description }}</template>
                    <span v-else class="text-muted-foreground/50">—</span>
                  </TableCell>
                  <TableCell class="py-3 text-cell text-muted-foreground">{{ fmtAge(f.uploaded_at) }}</TableCell>
                  <TableCell class="px-5 py-3 text-right">
                    <div class="inline-flex gap-1.5">
                      <Button size="sm" @click="replaceTarget = f">替换</Button>
                      <Button
                        variant="destructive"
                        size="sm"
                        :pending="del.isPending.value && del.variables.value === f.name"
                        pending-label="删除中…"
                        @click="confirmDelete(f)"
                      >
                        删除
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              </TableBody>
            </Table>
          </div>
        </template>
      </QueryState>
    </Card>

    <UploadSharedModal
      v-if="showUpload"
      @close="showUpload = false"
      @uploaded="onUploaded"
    />
    <UploadSharedModal
      v-if="replaceTarget"
      :lock-name="replaceTarget.name"
      :current-description="replaceTarget.description ?? ''"
      @close="replaceTarget = null"
      @uploaded="onUploaded"
    />
  </div>
</template>
