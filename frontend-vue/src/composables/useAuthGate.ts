// Singleton auth state. App.vue reads `ready` to gate the router; Login.vue
// drives the probe. OPEN-mode auto-skip stays identical to React: hit
// /api/admin/settings/info with the recovery latch suspended; if it answers
// without 401 the orchestrator runs without a token and we mark ready.

import { onMounted, onBeforeUnmount, ref } from "vue";
import { API, setToken, suspendAuthRecovery } from "../api";

const TOKEN_KEY = "sathop.token";

const ready = ref(!!localStorage.getItem(TOKEN_KEY));

function markReady() {
  ready.value = true;
}

export function useAuthGate() {
  // OPEN-mode probe runs once per consumer mount, but `ready` is shared so
  // re-probing on already-ready state is a no-op and skipped.
  let cancelled = false;

  function probeOpenMode() {
    if (ready.value) return;
    cancelled = false;
    suspendAuthRecovery(() => API.orchestratorInfo())
      .then(() => {
        if (cancelled) return;
        setToken("open");
        markReady();
      })
      .catch(() => {
        // 401 / network error → user must enter a token via Login.
      });
  }

  function onStorage() {
    ready.value = !!localStorage.getItem(TOKEN_KEY);
  }

  onMounted(() => {
    window.addEventListener("storage", onStorage);
    probeOpenMode();
  });

  onBeforeUnmount(() => {
    cancelled = true;
    window.removeEventListener("storage", onStorage);
  });

  return { ready, markReady };
}

export function logout(): void {
  localStorage.removeItem(TOKEN_KEY);
  window.location.reload();
}
