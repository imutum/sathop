import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter } from "react-router-dom";

import "./index.css";
import { App } from "./App";
import { ToastProvider } from "./toast";

const qc = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      staleTime: 30_000,
      // SSE (/api/stream) pushes invalidations. Long interval is just a safety
      // net for cases where the stream died and onerror never fired.
      refetchInterval: 60_000,
      refetchOnWindowFocus: true,
      refetchOnReconnect: true,
    },
  },
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <QueryClientProvider client={qc}>
        <ToastProvider>
          <App />
        </ToastProvider>
      </QueryClientProvider>
    </BrowserRouter>
  </StrictMode>,
);
