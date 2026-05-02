<script setup lang="ts">
import ConfirmDialog from "@/ui/ConfirmDialog.vue";
import Login from "@/pages/Login.vue";
import { Toaster as Sonner } from "@/components/ui/sonner";
import { useAuthGate } from "@/composables/useAuthGate";
// useTheme self-installs its <html> class watcher on first import.
import "@/composables/useTheme";

const { ready } = useAuthGate();
</script>

<template>
  <Login v-if="!ready" />
  <RouterView v-else />
  <ConfirmDialog />
  <Sonner position="bottom-right" rich-colors close-button />
</template>
