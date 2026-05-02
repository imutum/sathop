import { z } from "zod";

// Header-only schema for the "新建任务" form. Granule rows + credentials
// have dynamic shape (driven by the bundle manifest) and stay imperative
// in CreateBatchModal.vue — see validateRow / credsValid there.
export const createBatchHeaderSchema = z.object({
  batchId: z.string().min(1, "请填批次 ID"),
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
