<script setup lang="ts">
import { ref } from "vue";
import { useMutation } from "@tanstack/vue-query";
import { useForm } from "vee-validate";
import { toTypedSchema } from "@vee-validate/zod";
import { z } from "zod";
import { API, type BundleDetail } from "@/api";
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

const schema = toTypedSchema(
  z.object({
    file: z
      .custom<File>((v) => v instanceof File, "请选择一个 ZIP 文件")
      .refine((f) => f.name.toLowerCase().endsWith(".zip"), "文件需为 .zip 格式"),
    description: z.string().optional(),
  }),
);

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
  <Modal :dirty="meta.dirty" @close="emit('close')">
    <h2 class="font-display mb-5 text-lg font-semibold">上传任务包</h2>
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
              placeholder="简短说明这个 bundle 做什么"
            />
          </FormControl>
          <FormMessage />
        </FormItem>
      </FormField>
      <Alert v-if="submitError" variant="destructive">
        <AlertDescription>{{ submitError }}</AlertDescription>
      </Alert>
      <div class="flex justify-end gap-2 pt-2">
        <Button type="button" @click="emit('close')">取消</Button>
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
