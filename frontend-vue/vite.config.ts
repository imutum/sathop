import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";

export default defineConfig({
  plugins: [vue()],
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
        manualChunks: {
          echarts: ["echarts", "vue-echarts", "zrender"],
          vue: ["vue", "vue-router"],
          query: ["@tanstack/vue-query"],
        },
      },
    },
  },
});
