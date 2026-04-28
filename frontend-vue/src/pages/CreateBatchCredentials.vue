<script setup lang="ts">
import { hasCred } from "../credCache";
import { type CredDraft } from "./createBatchTypes";
import FieldLabel from "../ui/FieldLabel.vue";

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
    <div class="space-y-3 rounded-xl border border-border bg-subtle/40 p-3">
      <div
        v-for="name in names"
        :key="name"
        class="grid grid-cols-[140px_100px_1fr_2fr_auto] gap-2 items-center text-xs"
      >
        <label :for="`cred-${name}-secret`" class="font-mono" title="凭证名">
          {{ name }}
        </label>
        <select
          :id="`cred-${name}-scheme`"
          :aria-label="`${name} 凭证方案`"
          :value="draftFor(name).scheme"
          @change="
            update(name, {
              scheme: ($event.target as HTMLSelectElement).value as 'basic' | 'bearer',
            })
          "
          class="rounded-md border border-border bg-bg px-2 py-1 outline-none transition hover:border-accent/40 focus:border-accent"
        >
          <option value="basic">Basic</option>
          <option value="bearer">Bearer</option>
        </select>
        <input
          v-if="draftFor(name).scheme === 'basic'"
          :id="`cred-${name}-user`"
          :aria-label="`${name} 用户名`"
          autocomplete="off"
          :value="draftFor(name).username"
          @input="update(name, { username: ($event.target as HTMLInputElement).value })"
          placeholder="用户名"
          class="rounded-md border border-border bg-bg px-2 py-1 outline-none transition hover:border-accent/40 focus:border-accent"
        />
        <div v-else class="text-muted">—</div>
        <input
          :id="`cred-${name}-secret`"
          :aria-label="draftFor(name).scheme === 'basic' ? `${name} 密码` : `${name} Token`"
          autocomplete="off"
          type="password"
          :value="draftFor(name).secret"
          @input="update(name, { secret: ($event.target as HTMLInputElement).value })"
          :placeholder="draftFor(name).scheme === 'basic' ? '密码' : 'Token'"
          class="rounded-md border border-border bg-bg px-2 py-1 font-mono outline-none transition hover:border-accent/40 focus:border-accent"
        />
        <div class="flex items-center gap-2 whitespace-nowrap">
          <label
            :for="`cred-${name}-remember`"
            class="flex items-center gap-1 text-[11px] text-muted"
            title="勾选后，提交成功时把该凭证保存到本浏览器；下次新建任务自动填入。"
          >
            <input
              :id="`cred-${name}-remember`"
              type="checkbox"
              :checked="remember[name] ?? false"
              @change="emit('rememberChange', name, ($event.target as HTMLInputElement).checked)"
              class="accent-accent"
            />
            记住
          </label>
          <button
            v-if="hasCred(name)"
            type="button"
            @click="emit('forget', name)"
            class="text-[11px] text-muted hover:text-danger"
            title="从本浏览器删除已保存的凭证"
          >
            清除
          </button>
        </div>
      </div>
    </div>
    <div class="text-[11px] text-muted">
      凭证仅保存于本批次数据库行；worker 在 lease 时一次性取用。轮换 = 创建新批次。
      勾选"记住"后，凭证会被保存在本浏览器的 localStorage（明文，与登录 token 同等级别），下次新建任务自动填入。
    </div>
  </fieldset>
</template>
