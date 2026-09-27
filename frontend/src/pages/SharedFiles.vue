<script setup lang="ts">
import { ref } from "vue";
import { useMutation, useQuery, useQueryClient } from "@tanstack/vue-query";
import { API, type SharedFileInfo } from "@/api";
import { K } from "@/queryKeys";
import { fmtBytes } from "@/lib/format";
import { fmtAge } from "@/i18n";
import { requestConfirm } from "@/composables/useConfirm";
import { useToast } from "@/composables/useToast";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { DropdownMenuItem } from "@/components/ui/dropdown-menu";
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
import HintTip from "@/components/HintTip.vue";
import PageHeader from "@/components/PageHeader.vue";
import QueryState from "@/components/QueryState.vue";
import RowActions from "@/components/RowActions.vue";
import UploadSharedModal from "@/features/shared/components/UploadSharedModal.vue";
import { Icon } from "@/components/Icon";

const qc = useQueryClient();
const toast = useToast();
const showUpload = ref(false);
const replaceTarget = ref<SharedFileInfo | null>(null);

const list = useQuery({ queryKey: [...K.sharedFiles], queryFn: API.sharedFiles });

const del = useMutation({
  mutationFn: (name: string) => API.deleteSharedFile(name),
  onSuccess: (_r, name) => {
    qc.invalidateQueries({ queryKey: [...K.sharedFiles] });
    toast.success(`已删除 ${name}`);
  },
  onError: (e: Error) => toast.error(`删除失败：${e.message}`),
});

async function confirmDelete(f: SharedFileInfo) {
  const ok = await requestConfirm({
    title: `删除共享文件 ${f.name}？`,
    description: "仍被任务包引用的文件无法删除，请先解除引用。",
    confirmText: "删除",
    tone: "danger",
  });
  if (ok) del.mutate(f.name);
}

function onUploaded() {
  qc.invalidateQueries({ queryKey: [...K.sharedFiles] });
  showUpload.value = false;
  replaceTarget.value = null;
}
</script>

<template>
  <div class="space-y-6">
    <PageHeader title="共享文件">
      <template #description>
        管理任务包复用的辅助资源，如掩膜、DEM 和查找表
      </template>
      <template #actions>
        <Button variant="default" @click="showUpload = true" title="上传供任务包引用的共享文件">
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
            description='上传掩膜、DEM 或查找表，供任务包复用。'
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
              <RowActions align="end">
                <template #primary>
                  <Button size="sm" @click="replaceTarget = f">替换</Button>
                </template>
                <DropdownMenuItem
                  class="text-danger focus:bg-danger/10 focus:text-danger"
                  :disabled="del.isPending.value && del.variables.value === f.name"
                  @select="confirmDelete(f)"
                >
                  删除…
                </DropdownMenuItem>
              </RowActions>
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
                  <TableHead>上传</TableHead>
                  <TableHead class="px-5 text-right">操作</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                <TableRow v-for="f in files" :key="f.name">
                  <TableCell class="px-5 py-3 font-mono text-[12px] font-medium">
                    <span class="inline-flex items-center gap-1.5">
                      {{ f.name }}
                      <HintTip v-if="f.description" :text="f.description">
                        <span class="text-muted-foreground/70"><Icon name="info" :size="12" /></span>
                      </HintTip>
                    </span>
                  </TableCell>
                  <TableCell class="py-3 text-cell text-muted-foreground tabular-nums">
                    {{ fmtBytes(f.size) }}
                  </TableCell>
                  <TableCell class="py-3 text-cell">
                    <span class="font-mono" :title="f.sha256">{{ f.sha256.slice(0, 12) }}…</span>
                    <CopyButton :value="f.sha256" title="复制完整 SHA256" />
                  </TableCell>
                  <TableCell class="py-3 text-cell text-muted-foreground">{{ fmtAge(f.uploaded_at) }}</TableCell>
                  <TableCell class="px-5 py-3 text-right">
                    <RowActions align="end">
                      <template #primary>
                        <Button size="sm" @click="replaceTarget = f">替换</Button>
                      </template>
                      <DropdownMenuItem
                        class="text-danger focus:bg-danger/10 focus:text-danger"
                        :disabled="del.isPending.value && del.variables.value === f.name"
                        @select="confirmDelete(f)"
                      >
                        删除…
                      </DropdownMenuItem>
                    </RowActions>
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
