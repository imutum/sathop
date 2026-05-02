<script setup lang="ts">
import { computed, ref } from "vue";
import { useMutation } from "@tanstack/vue-query";
import { API, type BundleDetail } from "../api";
import { useToast } from "../composables/useToast";
import ActionButton from "../ui/ActionButton.vue";
import Alert from "../ui/Alert.vue";
import FieldLabel from "../ui/FieldLabel.vue";
import FilePicker from "../ui/FilePicker.vue";
import Modal from "../ui/Modal.vue";
import TextInput from "../ui/TextInput.vue";

const emit = defineEmits<{ close: []; uploaded: [d: BundleDetail] }>();

const toast = useToast();
const file = ref<File | null>(null);
const description = ref("");
const submitError = ref<string | null>(null);

const upload = useMutation({
  mutationFn: () => API.uploadBundle(file.value!, description.value || undefined),
  onSuccess: (d) => {
    toast.success(`已上传 ${d.name}@${d.version}`);
    emit("uploaded", d);
  },
  onError: (e: Error) => {
    submitError.value = e.message;
    toast.error(`上传失败：${e.message}`);
  },
});

const dirty = computed(() => !!file.value || description.value.trim() !== "");

function submit() {
  submitError.value = null;
  if (!file.value) {
    submitError.value = "请先选择一个 ZIP 文件";
    return;
  }
  upload.mutate();
}
</script>

<template>
  <Modal :dirty="dirty" @close="emit('close')">
    <h2 class="font-display mb-5 text-lg font-semibold">上传任务包</h2>
    <div class="space-y-4 text-sm">
      <label class="block">
        <FieldLabel required>ZIP 文件 · 内含 manifest.yaml</FieldLabel>
        <FilePicker v-model="file" accept=".zip" />
      </label>
      <label class="block">
        <FieldLabel>描述（可选）</FieldLabel>
        <TextInput
          v-model="description"
          placeholder="简短说明这个 bundle 做什么"
          class="mt-2"
        />
      </label>
      <Alert v-if="submitError">{{ submitError }}</Alert>
      <div class="flex justify-end gap-2 pt-2">
        <ActionButton @click="emit('close')">取消</ActionButton>
        <ActionButton
          tone="primary"
          @click="submit"
          :pending="upload.isPending.value"
          pending-label="上传中…"
        >
          上传
        </ActionButton>
      </div>
    </div>
  </Modal>
</template>
