import type { Config } from "tailwindcss";

export default {
  content: ["./index.html", "./src/**/*.{ts,vue}"],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        bg: "hsl(var(--bg) / <alpha-value>)",
        surface: "hsl(var(--surface) / <alpha-value>)",
        elevated: "hsl(var(--elevated) / <alpha-value>)",
        border: "hsl(var(--border) / <alpha-value>)",
        ring: "hsl(var(--ring) / <alpha-value>)",
        muted: "hsl(var(--muted) / <alpha-value>)",
        subtle: "hsl(var(--subtle) / <alpha-value>)",
        text: "hsl(var(--text) / <alpha-value>)",
        accent: "hsl(var(--accent) / <alpha-value>)",
        "accent-fg": "hsl(var(--accent-fg) / <alpha-value>)",
        "accent-soft": "hsl(var(--accent-soft) / <alpha-value>)",
        success: "hsl(var(--success) / <alpha-value>)",
        warning: "hsl(var(--warning) / <alpha-value>)",
        danger: "hsl(var(--danger) / <alpha-value>)",
      },
      fontFamily: {
        sans: [
          '"Geist"',
          '"Inter"',
          '"PingFang SC"',
          '"Microsoft YaHei"',
          "system-ui",
          "sans-serif",
        ],
        mono: [
          '"Geist Mono"',
          '"JetBrains Mono"',
          "ui-monospace",
          "SFMono-Regular",
          "Menlo",
          "monospace",
        ],
        display: ['"Geist"', '"Inter"', "system-ui", "sans-serif"],
      },
      boxShadow: {
        soft: "0 1px 2px 0 hsl(var(--shadow) / 0.06), 0 1px 3px 0 hsl(var(--shadow) / 0.08)",
        card: "0 1px 0 0 hsl(var(--surface-edge) / 1) inset, 0 1px 2px -1px hsl(var(--shadow) / 0.10), 0 4px 18px -10px hsl(var(--shadow) / 0.18)",
        pop: "0 12px 32px -8px hsl(var(--shadow) / 0.32), 0 4px 12px -4px hsl(var(--shadow) / 0.20)",
        glow: "0 0 0 1px hsl(var(--accent) / 0.30), 0 8px 30px -12px hsl(var(--accent) / 0.45)",
        "ring-soft": "0 0 0 4px hsl(var(--accent) / 0.12)",
      },
      borderRadius: {
        xl: "0.875rem",
        "2xl": "1.125rem",
      },
      keyframes: {
        "fade-in": {
          from: { opacity: "0", transform: "translateY(2px)" },
          to: { opacity: "1", transform: "translateY(0)" },
        },
        "scale-in": {
          from: { opacity: "0", transform: "scale(0.96)" },
          to: { opacity: "1", transform: "scale(1)" },
        },
        "slide-up": {
          from: { opacity: "0", transform: "translateY(8px)" },
          to: { opacity: "1", transform: "translateY(0)" },
        },
        pulse_soft: {
          "0%,100%": { opacity: "1" },
          "50%": { opacity: "0.55" },
        },
      },
      animation: {
        "fade-in": "fade-in 0.18s ease-out both",
        "scale-in": "scale-in 0.18s ease-out both",
        "slide-up": "slide-up 0.24s cubic-bezier(0.22,1,0.36,1) both",
        "pulse-soft": "pulse_soft 2.4s ease-in-out infinite",
      },
    },
  },
  plugins: [],
} satisfies Config;
