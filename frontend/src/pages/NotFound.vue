<script setup lang="ts">
import { useRoute, useRouter } from "vue-router";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";

const route = useRoute();
const router = useRouter();
</script>

<template>
  <div class="flex h-[60vh] items-center justify-center">
    <Card class="w-full max-w-md p-8 text-center">
      <div class="text-6xl font-semibold text-muted-foreground/40">404</div>
      <div class="mt-3 text-sm font-medium">页面不存在</div>
      <div class="mt-2 break-all rounded-lg border border-border bg-muted px-3 py-2 font-mono text-2xs text-muted-foreground">
        {{ route.fullPath }}
      </div>
      <Button class="mt-5" @click="router.push('/')">返回总览</Button>
    </Card>
  </div>
</template>
