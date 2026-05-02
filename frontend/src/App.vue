<script setup lang="ts">
import ToastContainer from "./ui/ToastContainer.vue";
import ConfirmDialog from "./ui/ConfirmDialog.vue";
import Login from "./Login.vue";
import { useAuthGate } from "./composables/useAuthGate";
// useTheme self-installs its <html> class watcher on first import.
import "./composables/useTheme";

const { ready } = useAuthGate();
</script>

<template>
  <Login v-if="!ready" />
  <RouterView v-else />
  <ConfirmDialog />
  <ToastContainer />
</template>
