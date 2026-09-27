<script setup lang="ts">
import { canRememberCredentials, hasCred } from "@/credCache";
import { type CredDraft } from "@/features/batch/credentials";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import FieldLabel from "@/components/FieldLabel.vue";
import SelectInput from "@/ui/SelectInput.vue";
import TextInput from "@/ui/TextInput.vue";

const props = defineProps<{
  names: string[];
  drafts: Record<string, CredDraft>;
  remember: Record<string, boolean>;
}>();

const canRemember = canRememberCredentials();

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
          <div
            class="flex items-center gap-1.5"
            :title="canRemember ? '提交成功后保存到当前浏览器，下次自动填入。' : '当前连接不支持记住凭证，请使用 HTTPS 访问。'"
          >
            <Checkbox
              :id="`cred-${name}-remember`"
              :model-value="remember[name] ?? false"
              :disabled="!canRemember"
              @update:model-value="(v: boolean | 'indeterminate') => emit('rememberChange', name, v === true)"
              class="h-3.5 w-3.5"
            />
            <Label
              :for="`cred-${name}-remember`"
              class="text-2xs font-normal text-muted-foreground"
            >
              记住
            </Label>
          </div>
          <Button
            v-if="hasCred(name)"
            type="button"
            variant="ghost"
            size="xs"
            class="text-2xs text-muted-foreground hover:text-danger"
            title="从本浏览器删除已保存的凭证"
            @click="emit('forget', name)"
          >
            清除
          </Button>
        </div>
      </div>
    </div>
    <div class="text-2xs text-muted-foreground">
      凭证用于本批次，随任务提供给工作节点。更新凭证请创建新批次。
      <template v-if="canRemember">勾选“记住”后将在当前浏览器保存并自动填入，请仅在可信设备上使用。</template>
      <template v-else>当前连接不支持记住凭证，本次仍可正常填写和提交。使用 HTTPS 访问后可启用。</template>
    </div>
  </fieldset>
</template>
