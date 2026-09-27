<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useQuery } from "@tanstack/vue-query";
import { useRoute, useRouter } from "vue-router";
import { refDebounced } from "@vueuse/core";
import { deliveryParams, serviceAPI } from "@/serviceWorkflows";
import { fmtBytes } from "@/lib/format";
import { useToast } from "@/composables/useToast";
import PageHeader from "@/components/PageHeader.vue";
import CopyButton from "@/components/CopyButton.vue";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

const route = useRoute();
const router = useRouter();
const toast = useToast();
const q = ref(typeof route.query.q === 'string' ? route.query.q : '');
const batch = ref(typeof route.query.batch === 'string' ? route.query.batch : '');
const start = ref('');
const end = ref('');
const search = refDebounced(q, 250);
const offset = ref(0);
const exporting = ref(false);
const rangeError = computed(() => start.value && end.value && start.value > end.value ? '开始日期不能晚于结束日期' : '');
const params = computed(() => deliveryParams(search.value, batch.value, start.value, end.value).toString());
watch(params, () => { offset.value = 0; });
watch([search, batch], () => {
  void router.replace({ query: { ...(search.value ? { q: search.value } : {}), ...(batch.value ? { batch: batch.value } : {}) } });
});
const query = useQuery({ queryKey: computed(() => ['deliveries', params.value, offset.value]),
  queryFn: () => serviceAPI.deliveries(params.value, offset.value), enabled: computed(() => !rangeError.value), refetchInterval: 60_000 });
const data = computed(() => query.data.value);
async function exportReport() {
  exporting.value = true;
  try { await serviceAPI.exportDeliveries(params.value); toast.success('已导出当前筛选下的全部交付记录'); }
  catch (e) { toast.error(e instanceof Error ? e.message : '导出失败'); }
  finally { exporting.value = false; }
}
function reset() { q.value = ''; batch.value = ''; start.value = ''; end.value = ''; offset.value = 0; }
</script>

<template>
  <div class="space-y-6">
    <PageHeader title="交付台账" description="按批次核对交付文件、接收端与校验值。任务明细清理或批次删除后，确认记录仍会保留。">
      <template #actions>
        <Button variant="outline" :disabled="query.isFetching.value" @click="query.refetch()">刷新</Button>
        <Button :disabled="exporting || !!rangeError || !data?.total || query.isFetching.value || q !== search" :pending="exporting" @click="exportReport">导出筛选结果</Button>
      </template>
    </PageHeader>
    <Card class="space-y-4 p-4">
      <div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <label class="space-y-1 text-xs text-muted-foreground">搜索<Input v-model="q" aria-label="搜索交付记录" maxlength="200" placeholder="批次、文件路径、接收端" /></label>
        <label class="space-y-1 text-xs text-muted-foreground">批次 ID<Input v-model="batch" aria-label="筛选批次 ID" maxlength="200" placeholder="留空查看全部批次" /></label>
        <label class="space-y-1 text-xs text-muted-foreground">开始日期<Input v-model="start" aria-label="开始日期" type="date" /></label>
        <label class="space-y-1 text-xs text-muted-foreground">结束日期（含当天）<Input v-model="end" aria-label="结束日期" type="date" /></label>
      </div>
      <div class="flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground">
        <span>日期按当前设备时区筛选。只记录接收端确认成功的文件。</span>
        <Button size="sm" variant="ghost" @click="reset">清空筛选</Button>
      </div>
      <p v-if="rangeError" role="alert" class="text-sm text-destructive">{{ rangeError }}</p>
    </Card>
    <div v-if="data && !rangeError" class="grid grid-cols-2 gap-3 md:grid-cols-4">
      <Card v-for="stat in [{ label: '交付文件', value: data.total.toLocaleString() }, { label: '交付体积', value: fmtBytes(data.total_bytes) }, { label: '数据粒', value: data.granules.toLocaleString() }, { label: '批次', value: data.batches.toLocaleString() }]" :key="stat.label" class="p-4">
        <div class="text-xs text-muted-foreground">{{ stat.label }}</div><div class="mt-2 text-xl font-semibold tabular-nums">{{ stat.value }}</div>
      </Card>
    </div>
    <p v-if="query.error.value" role="alert" class="text-sm text-destructive">加载失败：{{ query.error.value.message }} <button class="underline" @click="query.refetch()">重试</button></p>
    <p v-else-if="query.isPending.value && !rangeError" role="status" class="py-12 text-center text-muted-foreground">正在读取交付记录…</p>
    <Card v-else-if="data && !rangeError" class="overflow-hidden">
      <div v-if="!data.total" class="space-y-2 px-4 py-14 text-center"><p class="font-medium">没有符合条件的交付记录</p><p class="text-sm text-muted-foreground">调整筛选条件，或等待接收端完成首次交付确认。</p></div>
      <Table v-else>
        <TableHeader><TableRow><TableHead>批次 / 数据粒</TableHead><TableHead>产物与校验</TableHead><TableHead>大小</TableHead><TableHead>接收端 / 确认时间</TableHead></TableRow></TableHeader>
        <TableBody>
          <TableRow v-for="r in data.items" :key="r.id">
            <TableCell class="min-w-48 max-w-72 align-top"><RouterLink v-if="r.batch_exists" :to="`/batches/${encodeURIComponent(r.batch_id)}`" class="break-all font-medium text-primary hover:underline">{{ r.batch_name }}</RouterLink><span v-else class="break-all font-medium">{{ r.batch_name }} <span class="text-xs text-muted-foreground">（批次已删除）</span></span><div class="mt-1 break-all font-mono text-xs text-muted-foreground">{{ r.granule_id }}</div><div class="mt-1 break-all text-xs text-muted-foreground">{{ r.bundle_ref }}</div></TableCell>
            <TableCell class="min-w-56 max-w-96 align-top"><div class="break-all text-sm">{{ r.object_key }}</div><div class="mt-1 flex items-start gap-1"><code class="break-all text-2xs text-muted-foreground">{{ r.sha256 }}</code><CopyButton :value="r.sha256" title="复制 SHA-256" /></div></TableCell>
            <TableCell class="whitespace-nowrap align-top tabular-nums">{{ fmtBytes(r.size) }}</TableCell>
            <TableCell class="min-w-44 align-top"><div class="break-all text-sm">{{ r.receiver_id || '未记录' }}</div><div class="mt-1 whitespace-nowrap text-xs text-muted-foreground">{{ new Date(r.delivered_at).toLocaleString() }}</div></TableCell>
          </TableRow>
        </TableBody>
      </Table>
      <div v-if="data.total" class="flex flex-wrap items-center justify-between gap-3 border-t border-border px-4 py-3 text-xs text-muted-foreground">
        <span>第 {{ offset + 1 }}–{{ Math.min(offset + 20, data.total) }} 条，共 {{ data.total }} 条</span>
        <div class="flex gap-2"><Button size="sm" variant="outline" :disabled="offset === 0 || query.isFetching.value" @click="offset -= 20">上一页</Button><Button size="sm" variant="outline" :disabled="offset + 20 >= data.total || query.isFetching.value" @click="offset += 20">下一页</Button></div>
      </div>
    </Card>
    <p class="text-xs leading-relaxed text-muted-foreground">台账从本功能启用后持续留存，并补录升级时仍存在的确认记录。升级前已清理的历史明细无法恢复，因此这里的文件数可能与批次累计交付数不同。接收确认是交付凭据，产品内容仍需按客户要求验收。</p>
  </div>
</template>
