<script setup lang="ts">
import { hasCred } from "@/credCache";
import { type CredDraft } from "@/features/batch/types";
import FieldLabel from "@/components/FieldLabel.vue";
import SelectInput from "@/ui/SelectInput.vue";
import TextInput from "@/ui/TextInput.vue";

const props = defineProps<{
  names: string[];
  drafts: Record<string, CredDraft>;
  remember: Record<string, boolean>;
}>();

const emit = defineEmits<{
  change: [name: string, d: CredDraft];
  rememberChange: [name: string, v: boolean];
  forget: [name: string];
}>();

function draftFor(name: string): CredDraft {
  return props.drafts[name] ?? { scheme: "basic", username: "", secret: "" };
}

function update(name: string, patch: Partial<CredDraft>) {
  emit("change", name, { ...draftFor(name), ...patch });
}
</script>

<template>
  <fieldset class="space-y-2">
    <legend><FieldLabel>凭证 · 任务包需要 {{ names.length }} 个</FieldLabel></legend>
    <div class="space-y-3 rounded-lg border border-border bg-muted/40 p-3">
      <div
        v-for="name in names"
        :key="name"
        class="grid grid-cols-[140px_100px_1fr_2fr_auto] gap-2 items-center text-xs"
      >
        <label :for="`cred-${name}-secret`" class="font-mono" title="凭证名">
          {{ name }}
        </label>
        <SelectInput
          :id="`cred-${name}-scheme`"
          :aria-label="`${name} 凭证方案`"
          :model-value="draftFor(name).scheme"
          @update:model-value="
            update(name, {
              scheme: $event as 'basic' | 'bearer',
            })
          "
        >
          <option value="basic">Basic</option>
          <option value="bearer">Bearer</option>
        </SelectInput>
        <TextInput
          v-if="draftFor(name).scheme === 'basic'"
          :id="`cred-${name}-user`"
          :aria-label="`${name} 用户名`"
          autocomplete="off"
          :model-value="draftFor(name).username"
          @update:model-value="update(name, { username: $event })"
          placeholder="用户名"
        />
        <div v-else class="text-muted-foreground">—</div>
        <TextInput
          :id="`cred-${name}-secret`"
          :aria-label="draftFor(name).scheme === 'basic' ? `${name} 密码` : `${name} Token`"
          autocomplete="off"
          type="password"
          :model-value="draftFor(name).secret"
          @update:model-value="update(name, { secret: $event })"
          :placeholder="draftFor(name).scheme === 'basic' ? '密码' : 'Token'"
          class="font-mono"
        />
        <div class="flex items-center gap-2 whitespace-nowrap">
          <label
            :for="`cred-${name}-remember`"
            class="flex items-center gap-1 text-[11px] text-muted-foreground"
            title="勾选后，提交成功时把该凭证保存到本浏览器；下次新建任务自动填入。"
          >
            <input
              :id="`cred-${name}-remember`"
              type="checkbox"
              :checked="remember[name] ?? false"
              @change="emit('rememberChange', name, ($event.target as HTMLInputElement).checked)"
              class="accent-primary"
            />
            记住
          </label>
          <button
            v-if="hasCred(name)"
            type="button"
            @click="emit('forget', name)"
            class="text-[11px] text-muted-foreground hover:text-danger"
            title="从本浏览器删除已保存的凭证"
          >
            清除
          </button>
        </div>
      </div>
    </div>
    <div class="text-[11px] text-muted-foreground">
      凭证仅保存于本批次数据库行；worker 在 lease 时一次性取用。轮换 = 创建新批次。
      勾选"记住"后，凭证会被保存在本浏览器的 localStorage（明文，与登录 token 同等级别），下次新建任务自动填入。
    </div>
  </fieldset>
</template>
