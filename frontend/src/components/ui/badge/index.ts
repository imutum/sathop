import type { VariantProps } from "class-variance-authority"
import { cva } from "class-variance-authority"

export { default as Badge } from "./Badge.vue"

// State-driven tone palette (GranuleState / EventLevel / nodeStatusBadge).
// Caller passes string via :tone prop; unknown values fall back to "info".
// Keys mirror the React port; do not rename without coordinating callers.
// All classes self-contain bg + text (border-transparent comes from cva base).
export const BADGE_TONES = {
  pending: "bg-muted text-muted-foreground",
  queued: "bg-amber-500/10 text-amber-600 dark:text-amber-300",
  downloading: "bg-sky-500/10 text-sky-600 dark:text-sky-300",
  downloaded: "bg-sky-500/10 text-sky-600 dark:text-sky-300",
  processing: "bg-indigo-500/10 text-indigo-600 dark:text-indigo-300",
  processed: "bg-indigo-500/10 text-indigo-600 dark:text-indigo-300",
  uploaded: "bg-violet-500/10 text-violet-600 dark:text-violet-300",
  acked: "bg-success/10 text-success",
  deleted: "bg-success/10 text-success",
  failed: "bg-danger/10 text-danger",
  blacklisted: "bg-danger/15 text-danger",
  info: "bg-muted text-muted-foreground",
  warn: "bg-warning/12 text-warning",
  error: "bg-danger/12 text-danger",
} as const

export type BadgeTone = keyof typeof BADGE_TONES

export const badgeVariants = cva(
  "inline-flex items-center gap-1 rounded-md border px-2.5 py-0.5 text-xs font-semibold transition-colors focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2",
  {
    variants: {
      variant: {
        default:
          "border-transparent bg-primary text-primary-foreground shadow hover:bg-primary/80",
        secondary:
          "border-transparent bg-secondary text-secondary-foreground hover:bg-secondary/80",
        destructive:
          "border-transparent bg-destructive text-destructive-foreground shadow hover:bg-destructive/80",
        outline: "text-foreground",
        success: "border-transparent bg-success/15 text-success",
        warning: "border-transparent bg-warning/15 text-warning",
        info: "border-transparent bg-muted text-muted-foreground",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  },
)

export type BadgeVariants = VariantProps<typeof badgeVariants>
