import { z } from "zod";

export const uploadBundleSchema = z.object({
  file: z
    .custom<File>((v) => v instanceof File, "请选择一个 ZIP 文件")
    .refine((f) => f.name.toLowerCase().endsWith(".zip"), "文件需为 .zip 格式"),
  description: z.string().optional(),
});

export type UploadBundleInput = z.infer<typeof uploadBundleSchema>;
