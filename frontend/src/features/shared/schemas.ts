import { z } from "zod";

// Mirrors the orchestrator's name validation in api/shared.py: starts with
// alphanumeric; allows alphanumeric, `.`, `_`, `-`; max 255 chars.
export const SHARED_NAME_RE = /^[A-Za-z0-9][A-Za-z0-9._-]{0,254}$/;

export const uploadSharedSchema = z.object({
  name: z
    .string()
    .min(1, "请填写名称")
    .regex(SHARED_NAME_RE, "名称不合法：仅允许字母数字和 . _ -，不能以点开头，最长 255 字节"),
  file: z.custom<File>((v) => v instanceof File, "请选择文件"),
  description: z.string().optional(),
});

export type UploadSharedInput = z.infer<typeof uploadSharedSchema>;
