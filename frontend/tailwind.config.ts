import type { Config } from "tailwindcss";
import animate from "tailwindcss-animate";

export default {
  content: ["./index.html", "./src/**/*.{ts,vue}"],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        background: "hsl(var(--background) / <alpha-value>)",
        foreground: "hsl(var(--foreground) / <alpha-value>)",
        card: {
          DEFAULT: "hsl(var(--card) / <alpha-value>)",
          foreground: "hsl(var(--card-foreground) / <alpha-value>)",
        },
        popover: {
          DEFAULT: "hsl(var(--popover) / <alpha-value>)",
          foreground: "hsl(var(--popover-foreground) / <alpha-value>)",
        },
        primary: {
          DEFAULT: "hsl(var(--primary) / <alpha-value>)",
          foreground: "hsl(var(--primary-foreground) / <alpha-value>)",
        },
        secondary: {
          DEFAULT: "hsl(var(--secondary) / <alpha-value>)",
          foreground: "hsl(var(--secondary-foreground) / <alpha-value>)",
        },
        muted: {
          DEFAULT: "hsl(var(--muted) / <alpha-value>)",
          foreground: "hsl(var(--muted-foreground) / <alpha-value>)",
        },
        accent: {
          DEFAULT: "hsl(var(--accent) / <alpha-value>)",
          foreground: "hsl(var(--accent-foreground) / <alpha-value>)",
        },
        destructive: {
          DEFAULT: "hsl(var(--destructive) / <alpha-value>)",
          foreground: "hsl(var(--destructive-foreground) / <alpha-value>)",
        },
        border: "hsl(var(--border) / <alpha-value>)",
        input: "hsl(var(--input) / <alpha-value>)",
        ring: "hsl(var(--ring) / <alpha-value>)",

        success: "hsl(var(--success) / <alpha-value>)",
        warning: "hsl(var(--warning) / <alpha-value>)",
        danger: "hsl(var(--danger) / <alpha-value>)",
        signal: "hsl(var(--signal) / <alpha-value>)",
      },
      borderRadius: {
        lg: "var(--radius)",
        md: "calc(var(--radius) - 2px)",
        sm: "calc(var(--radius) - 4px)",
        xl: "0.5rem",
        "2xl": "0.5rem",
      },
      fontSize: {
        // Sub-text-xs scale for the dense ops UI. Names match Shadboard's
        // mini convention but tuned for tabular density.
        //
        //   3xs   10px    smallest captions (corner coords, footer credits)
        //   mini  10.5px  uppercase mini-labels (Field / Stat / kbd)
        //   2xs   11px    dense small UI
        //   cell  11.5px  mono table cells / row metadata
        "3xs": ["10px", "13px"],
        mini: ["10.5px", "14px"],
        "2xs": ["11px", "15px"],
        cell: ["11.5px", "16px"],
      },
      letterSpacing: {
        label: "0.14em",
        brand: "0.22em",
        section: "0.20em",
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
          '"JetBrains Mono"',
          '"Geist Mono"',
          "ui-monospace",
          "SFMono-Regular",
          "Menlo",
          "monospace",
        ],
        display: ['"Fraunces"', '"Times New Roman"', "serif"],
      },
      boxShadow: {
        soft: "0 1px 2px 0 hsl(var(--shadow) / 0.06)",
        card: "0 1px 0 0 hsl(var(--shadow) / 0.04), 0 1px 2px 0 hsl(var(--shadow) / 0.05)",
        pop: "0 12px 32px -16px hsl(var(--shadow) / 0.30), 0 4px 10px -6px hsl(var(--shadow) / 0.18)",
        glow: "0 0 0 1px hsl(var(--primary) / 0.18), 0 0 24px -4px hsl(var(--primary) / 0.20)",
        "ring-soft": "0 0 0 4px hsl(var(--primary) / 0.14)",
        "inset-rule": "inset 0 -1px 0 0 hsl(var(--rule-soft))",
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
        sweep: {
          "0%": { transform: "translateX(-100%)" },
          "100%": { transform: "translateX(100%)" },
        },
        "accordion-down": {
          from: { height: "0" },
          to: { height: "var(--reka-accordion-content-height)" },
        },
        "accordion-up": {
          from: { height: "var(--reka-accordion-content-height)" },
          to: { height: "0" },
        },
      },
      animation: {
        "fade-in": "fade-in 0.18s ease-out both",
        "scale-in": "scale-in 0.18s ease-out both",
        "slide-up": "slide-up 0.24s cubic-bezier(0.22,1,0.36,1) both",
        "pulse-soft": "pulse_soft 2.4s ease-in-out infinite",
        sweep: "sweep 1.6s linear infinite",
        "accordion-down": "accordion-down 0.2s ease-out",
        "accordion-up": "accordion-up 0.2s ease-out",
      },
    },
  },
  plugins: [animate],
} satisfies Config;
