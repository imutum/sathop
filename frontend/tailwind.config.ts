import type { Config } from "tailwindcss";

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: "#0b0f17",
        surface: "#131922",
        border: "#1f2937",
        muted: "#64748b",
        text: "#e2e8f0",
        accent: "#3b82f6",
      },
      fontFamily: {
        mono: ['"JetBrains Mono"', "ui-monospace", "monospace"],
      },
    },
  },
  plugins: [],
} satisfies Config;
