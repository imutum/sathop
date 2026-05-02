<script setup lang="ts">
import { useRoute, useRouter } from "vue-router";

const route = useRoute();
const router = useRouter();
</script>

<template>
  <div class="flex h-[60vh] items-center justify-center">
    <div class="w-full max-w-md rounded-lg border border-border bg-background p-8 text-center shadow-card">
      <div class="font-display text-6xl font-semibold text-muted-foreground/40">404</div>
      <div class="mt-3 text-sm font-medium">页面不存在</div>
      <div class="mt-2 break-all rounded-lg border border-border bg-muted px-3 py-2 font-mono text-2xs text-muted-foreground">
        {{ route.fullPath }}
      </div>
      <button
        type="button"
        @click="router.push('/')"
        class="mt-5 inline-flex items-center gap-1.5 rounded-lg bg-primary px-3.5 py-2 text-sm font-medium text-primary-foreground transition hover:bg-primary/90"
      >
        返回总览
      </button>
    </div>
  </div>
</template>
