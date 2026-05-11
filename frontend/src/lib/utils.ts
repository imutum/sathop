import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

// Internal granule_id is `<batch_id>:<user_gid>`; UI shows the user-supplied
// portion alone. Returns gid unchanged when the prefix is absent (e.g. a
// pre-prefix legacy row).
export function stripBatchPrefix(gid: string, batchId: string): string {
  return gid.startsWith(`${batchId}:`) ? gid.slice(batchId.length + 1) : gid;
}
