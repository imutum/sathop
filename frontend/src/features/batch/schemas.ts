import { z } from "zod";

// Header-only schema for the "新建任务" form. Bundle-driven row and credential
// checks live in types.ts helpers and are composed by CreateBatchModal.vue.
export const createBatchHeaderSchema = z.object({
  name: z.string().min(1, "请填展示名称"),
  bundleSel: z.string().min(1, "请选择任务包"),
  targetReceiver: z.string().optional(),
  envText: z
    .string()
    .optional()
    .refine((v) => {
      if (!v?.trim()) return true;
      try {
        const parsed = JSON.parse(v);
        return typeof parsed === "object" && parsed !== null && !Array.isArray(parsed);
      } catch {
        return false;
      }
    }, "环境变量必须是 JSON 对象 {KEY: value}"),
});

export type CreateBatchHeaderInput = z.infer<typeof createBatchHeaderSchema>;
