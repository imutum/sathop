<script setup lang="ts">
import { computed, ref } from "vue";
import { useQuery } from "@tanstack/vue-query";
import { serviceAPI, type TaskTemplate } from "@/serviceWorkflows";
import { parseExecutionEnv } from "@/features/batch/serialization";
import { requestConfirm } from "@/composables/useConfirm";
import { useToast } from "@/composables/useToast";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import SelectInput from "@/ui/SelectInput.vue";

const props = defineProps<{ bundleRef: string; receiverId: string; envText: string }>();
const emit = defineEmits<{ apply: [template: TaskTemplate] }>();
const templates = useQuery({ queryKey: ["task-templates"], queryFn: serviceAPI.templates, staleTime: 0 });
const selected = ref("");
const name = ref("");
const includeEnv = ref(false);
const busy = ref(false);
const error = ref("");
const toast = useToast();
const current = computed(() => templates.data.value?.find((template) => template.template_id === selected.value));
const canSave = computed(() => !busy.value && !!name.value.trim() && props.bundleRef !== "orch:");

async function runAction(action: () => Promise<void>, fallbackError: string) {
  busy.value = true;
  error.value = "";
  try {
    await action();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : fallbackError;
  } finally {
    busy.value = false;
  }
}

async function save(update: boolean) {
  if (update) {
    const confirmed = await requestConfirm({
      title: "更新这个任务模板？",
      description: "将用当前任务包、接收端和勾选的环境变量替换原配置，已创建任务不受影响。",
      confirmText: "更新模板",
    });
    if (!confirmed) return;
  }
  await runAction(async () => {
    const saved = await serviceAPI.saveTemplate(
      {
        name: name.value.trim(),
        bundle_ref: props.bundleRef,
        target_receiver_id: props.receiverId || null,
        execution_env: includeEnv.value ? parseExecutionEnv(props.envText, { strict: true }) : {},
      },
      update ? selected.value : undefined,
    );
    await templates.refetch();
    selected.value = saved.template_id;
    toast.success(update ? "模板已更新" : "模板已保存，下次可直接套用");
  }, "模板保存失败");
}

async function remove() {
  if (!current.value) return;
  const confirmed = await requestConfirm({
    title: `删除模板“${current.value.name}”？`,
    description: "已创建的批次和本次表单不会改变。",
    confirmText: "删除模板",
    tone: "danger",
  });
  if (!confirmed) return;
  await runAction(async () => {
    await serviceAPI.deleteTemplate(selected.value);
    selected.value = "";
    name.value = "";
    await templates.refetch();
    toast.success("模板已删除");
  }, "删除失败");
}
</script>

<template>
  <details class="group mb-6 rounded-xl border border-dashed border-border bg-muted/20 text-sm">
    <summary class="cursor-pointer px-4 py-3 text-xs font-medium text-muted-foreground hover:text-foreground">任务模板 <span class="ml-2 font-normal">套用或保存常用配置</span></summary>
    <div class="space-y-3 border-t border-dashed p-4">
      <div class="flex flex-wrap items-center gap-2">
        <SelectInput
          v-model="selected"
          aria-label="选择任务模板"
          class="min-w-0 flex-1 basis-48"
          :disabled="busy"
          @change="name = current?.name ?? ''"
        >
          <option value="">{{ templates.isPending.value ? '正在加载…' : '选择已保存的配置' }}</option>
          <option v-for="template in templates.data.value ?? []" :key="template.template_id" :value="template.template_id">
            {{ template.name }}
          </option>
        </SelectInput>
        <Button type="button" variant="outline" :disabled="!current || busy" @click="current && emit('apply', current)">
          套用配置
        </Button>
        <Button v-if="current" type="button" variant="ghost" :disabled="busy" @click="remove">
          删除模板
        </Button>
      </div>
      <div v-if="templates.error.value" role="alert" class="text-destructive">
        模板加载失败。<button type="button" class="underline" @click="templates.refetch()">重试</button>
      </div>
      <p v-if="current" class="break-all text-xs text-muted-foreground">
        {{ current.bundle_ref }} · {{ current.target_receiver_id || '自动分配接收端' }} ·
        {{ Object.keys(current.execution_env).length }} 个环境变量
      </p>
      <details>
        <summary class="cursor-pointer text-xs text-muted-foreground">将当前配置保存为模板</summary>
        <div class="mt-3 space-y-3">
          <Input v-model="name" aria-label="模板名称" maxlength="100" placeholder="模板名称，例如：月度地表反射率处理" />
          <label class="flex items-center gap-2 text-xs">
            <input v-model="includeEnv" type="checkbox" />保存高级环境变量（请确认其中没有密码或令牌）
          </label>
          <p class="text-xs text-muted-foreground">
            保存任务包版本和接收端。批次名称、输入数据和下载凭证需在新任务中填写。模板保存在服务器上。
          </p>
          <div class="flex flex-wrap gap-2">
            <Button type="button" variant="outline" :disabled="!canSave" @click="save(false)">
              保存为新模板
            </Button>
            <Button v-if="current" type="button" variant="outline" :disabled="!canSave" @click="save(true)">
              更新所选模板
            </Button>
          </div>
        </div>
      </details>
      <p v-if="error" role="alert" class="whitespace-pre-wrap text-xs text-destructive">{{ error }}</p>
    </div>
  </details>
</template>
