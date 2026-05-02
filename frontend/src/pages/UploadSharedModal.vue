<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useMutation } from "@tanstack/vue-query";
import { API, type SharedFileInfo } from "../api";
import { useToast } from "../composables/useToast";
import ActionButton from "../ui/ActionButton.vue";
import Alert from "../ui/Alert.vue";
import FieldLabel from "../ui/FieldLabel.vue";
import FilePicker from "../ui/FilePicker.vue";
import Modal from "../ui/Modal.vue";
import TextInput from "../ui/TextInput.vue";

const NAME_RE = /^[A-Za-z0-9][A-Za-z0-9._-]{0,254}$/;

const props = withDefaults(
  defineProps<{ lockName?: string; currentDescription?: string }>(),
  { currentDescription: "" },
);

const emit = defineEmits<{ close: []; uploaded: [d: SharedFileInfo] }>();

const toast = useToast();
const file = ref<File | null>(null);
const name = ref(props.lockName ?? "");
const description = ref(props.currentDescription);
const submitError = ref<string | null>(null);

// Auto-fill the name field from the picked filename — but only on a fresh
// upload (lockName empty) and only when the user hasn't typed a name yet.
watch(file, (f) => {
  if (f && !props.lockName && !name.value) name.value = f.name;
});

const upload = useMutation({
  mutationFn: () => API.uploadSharedFile(name.value, file.value!, description.value || undefined),
  onSuccess: (d) => {
    toast.success(props.lockName ? `已替换 ${d.name}` : `已上传 ${d.name}`);
    emit("uploaded", d);
  },
  onError: (e: Error) => {
    submitError.value = e.message;
    toast.error(`上传失败：${e.message}`);
  },
});

const dirty = computed(
  () =>
    !!file.value ||
    name.value !== (props.lockName ?? "") ||
    description.value !== props.currentDescription,
);

function submit() {
  submitError.value = null;
  if (!file.value) return (submitError.value = "请先选择文件");
  if (!name.value) return (submitError.value = "请填写名称");
  if (!NAME_RE.test(name.value)) {
    return (submitError.value =
      "名称不合法：仅允许字母数字和 . _ -，不能以点开头，最长 255 字节。");
  }
  upload.mutate();
}
</script>

<template>
  <Modal :dirty="dirty" @close="emit('close')">
    <h2 class="font-display mb-5 text-lg font-semibold">
      {{ lockName ? `替换 ${lockName}` : "上传共享文件" }}
    </h2>
    <div class="space-y-4 text-sm">
      <label class="block">
        <FieldLabel required>名称</FieldLabel>
        <TextInput
          v-model="name"
          :disabled="!!lockName"
          placeholder="mask.tif"
          class="mt-2 font-mono text-xs"
        />
        <div class="mt-1.5 text-[10.5px] text-muted/80">
          允许字符：字母、数字、<code>.</code> <code>_</code> <code>-</code>；不能以点开头；最长 255 字节。
        </div>
      </label>
      <label class="block">
        <FieldLabel required>文件</FieldLabel>
        <FilePicker v-model="file" />
      </label>
      <label class="block">
        <FieldLabel>描述（可选）</FieldLabel>
        <TextInput
          v-model="description"
          placeholder="简短说明这个文件是什么"
          class="mt-2"
        />
      </label>
      <Alert v-if="submitError">{{ submitError }}</Alert>
      <div class="flex justify-end gap-2 pt-2">
        <ActionButton @click="emit('close')">取消</ActionButton>
        <ActionButton
          tone="primary"
          :pending="upload.isPending.value"
          pending-label="上传中…"
          @click="submit"
        >
          {{ lockName ? "替换" : "上传" }}
        </ActionButton>
      </div>
    </div>
  </Modal>
</template>
