import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8765",
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: "dist",
    rollupOptions: {
      output: {
        // Split heavy vendors so the initial bundle stays small and the
        // browser can fetch chunks in parallel. Cache stays warm across
        // app updates because vendors rarely change.
        manualChunks: {
          echarts: ["echarts", "echarts-for-react", "zrender"],
          react: ["react", "react-dom", "react-router-dom"],
          query: ["@tanstack/react-query"],
        },
      },
    },
  },
});
