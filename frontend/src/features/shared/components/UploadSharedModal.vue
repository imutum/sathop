<script setup lang="ts">
import { ref } from "vue";
import { useMutation } from "@tanstack/vue-query";
import { useForm } from "vee-validate";
import { toTypedSchema } from "@vee-validate/zod";
import { z } from "zod";
import { API, type SharedFileInfo } from "@/api";
import { useToast } from "@/composables/useToast";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  FormControl,
  FormDescription,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import FilePicker from "@/components/FilePicker.vue";
import Modal from "@/ui/Modal.vue";

const NAME_RE = /^[A-Za-z0-9][A-Za-z0-9._-]{0,254}$/;

const props = withDefaults(
  defineProps<{ lockName?: string; currentDescription?: string }>(),
  { currentDescription: "" },
);

const emit = defineEmits<{ close: []; uploaded: [d: SharedFileInfo] }>();

const toast = useToast();
const submitError = ref<string | null>(null);

const schema = toTypedSchema(
  z.object({
    name: z
      .string()
      .min(1, "请填写名称")
      .regex(NAME_RE, "名称不合法：仅允许字母数字和 . _ -，不能以点开头，最长 255 字节"),
    file: z.custom<File>((v) => v instanceof File, "请选择文件"),
    description: z.string().optional(),
  }),
);

const { handleSubmit, meta, setFieldValue, values } = useForm({
  validationSchema: schema,
  initialValues: {
    name: props.lockName ?? "",
    file: null as unknown as File,
    description: props.currentDescription,
  },
});

// On a fresh upload (no lockName), auto-fill `name` with the picked filename
// — but only if the user hasn't typed anything yet.
function onPickFile(f: File | null) {
  setFieldValue("file", f as File);
  if (f && !props.lockName && !values.name) setFieldValue("name", f.name);
}

const upload = useMutation({
  mutationFn: (input: { name: string; file: File; description?: string }) =>
    API.uploadSharedFile(input.name, input.file, input.description),
  onSuccess: (d) => {
    toast.success(props.lockName ? `已替换 ${d.name}` : `已上传 ${d.name}`);
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
    name: vals.name,
    file: vals.file as File,
    description: vals.description?.trim() || undefined,
  });
});
</script>

<template>
  <Modal :dirty="meta.dirty" @close="emit('close')">
    <h2 class="font-display mb-5 text-lg font-semibold">
      {{ lockName ? `替换 ${lockName}` : "上传共享文件" }}
    </h2>
    <form class="space-y-4 text-sm" @submit.prevent="onSubmit">
      <FormField v-slot="{ componentField }" name="name">
        <FormItem>
          <FormLabel>名称</FormLabel>
          <FormControl>
            <Input
              v-bind="componentField"
              :disabled="!!lockName"
              placeholder="mask.tif"
              class="font-mono text-xs"
            />
          </FormControl>
          <FormDescription>
            允许字符：字母、数字、<code>.</code> <code>_</code> <code>-</code>；不能以点开头；最长 255 字节。
          </FormDescription>
          <FormMessage />
        </FormItem>
      </FormField>

      <FormField v-slot="{ value }" name="file">
        <FormItem>
          <FormLabel>文件</FormLabel>
          <FormControl>
            <FilePicker
              :model-value="(value as File | null) ?? null"
              @update:model-value="onPickFile"
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
              placeholder="简短说明这个文件是什么"
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
          {{ lockName ? "替换" : "上传" }}
        </Button>
      </div>
    </form>
  </Modal>
</template>
