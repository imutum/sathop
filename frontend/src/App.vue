<script setup lang="ts">
import ConfirmDialog from "@/ui/ConfirmDialog.vue";
import Login from "@/pages/Login.vue";
import { Toaster as Sonner } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import { useAuthGate } from "@/composables/useAuthGate";
// useTheme self-installs its <html> class watcher on first import.
import "@/composables/useTheme";

const { ready } = useAuthGate();
</script>

<template>
  <!-- One global TooltipProvider so any descendant <Tooltip> / <HintTip>
       shares the same delay/skip-grace timing. 200ms keeps the dense admin
       UI snappy without firing on incidental hover passes. -->
  <TooltipProvider :delay-duration="200" :skip-delay-duration="100">
    <Login v-if="!ready" />
    <RouterView v-else />
    <ConfirmDialog />
    <Sonner position="bottom-right" rich-colors close-button />
  </TooltipProvider>
</template>
