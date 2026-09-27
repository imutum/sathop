<script setup lang="ts">
import { ref } from "vue";
import { useMutation } from "@tanstack/vue-query";
import { useForm } from "vee-validate";
import { toTypedSchema } from "@vee-validate/zod";
import { API, type BundleDetail } from "@/api";
import { uploadBundleSchema } from "@/features/bundle/schemas";
import { useToast } from "@/composables/useToast";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import FilePicker from "@/components/FilePicker.vue";
import Modal from "@/ui/Modal.vue";

const emit = defineEmits<{ close: []; uploaded: [d: BundleDetail] }>();

const toast = useToast();
const submitError = ref<string | null>(null);

const schema = toTypedSchema(uploadBundleSchema);

const { handleSubmit, meta } = useForm({
  validationSchema: schema,
  // File starts unset; zod's `instanceof(File)` rejects null at submit time.
  initialValues: { file: null as unknown as File, description: "" },
});

const upload = useMutation({
  mutationFn: (input: { file: File; description?: string }) =>
    API.uploadBundle(input.file, input.description),
  onSuccess: (d) => {
    toast.success(`已上传 ${d.name}@${d.version}`);
    emit("uploaded", d);
  },
  onError: (e: Error) => {
    submitError.value = e.message;
    toast.error(`上传失败：${e.message}`);
  },
});

const onSubmit = handleSubmit((vals) => {
  submitError.value = null;
  upload.mutate({
    file: vals.file as File,
    description: vals.description?.trim() || undefined,
  });
});
</script>

<template>
  <Modal v-slot="{ close }" title="上传任务包" description="上传处理脚本与执行配置，供批次使用。" :dirty="meta.dirty" @close="emit('close')">
    <form class="space-y-4 text-sm" @submit.prevent="onSubmit">
      <FormField v-slot="{ value, handleChange }" name="file">
        <FormItem>
          <FormLabel>ZIP 文件 · 内含 manifest.yaml</FormLabel>
          <FormControl>
            <FilePicker
              :model-value="(value as File | null) ?? null"
              accept=".zip"
              @update:model-value="handleChange"
            />
          </FormControl>
          <FormMessage />
        </FormItem>
      </FormField>
      <FormField v-slot="{ componentField }" name="description">
        <FormItem>
          <FormLabel>描述（可选）</FormLabel>
          <FormControl>
            <Input
              v-bind="componentField"
              placeholder="简述任务包的处理用途"
            />
          </FormControl>
          <FormMessage />
        </FormItem>
      </FormField>
      <Alert v-if="submitError" variant="destructive">
        <AlertDescription>{{ submitError }}</AlertDescription>
      </Alert>
      <div class="modal-actions">
        <Button type="button" variant="outline" @click="close">取消</Button>
        <Button
          type="submit"
          variant="default"
          :pending="upload.isPending.value"
          pending-label="上传中…"
        >
          上传
        </Button>
      </div>
    </form>
  </Modal>
</template>
