import { createApp } from "vue";
import { VueQueryPlugin, QueryClient } from "@tanstack/vue-query";

import "./index.css";
import App from "./App.vue";
import { router } from "./router";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      staleTime: 30_000,
      // SSE drives most refreshes; window-focus + reconnect cover the rest.
      // Long interval is a safety net only when the stream is dead.
      refetchInterval: 5 * 60_000,
      refetchOnWindowFocus: true,
      refetchOnReconnect: true,
    },
  },
});

createApp(App)
  .use(router)
  .use(VueQueryPlugin, { queryClient })
  .mount("#app");
