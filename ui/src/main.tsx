import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { ScreenErrorBoundary } from "./ScreenErrorBoundary";
import { initializeToken } from "./api";
// nibi, vendored by scripts/sync_nibi.py. Japanese-only UI: the core without @font-face,
// plus IBM Plex Sans JP alone (no Lexend). ABAR's layout comes after it.
import "../vendor/nibi/dist/web/nibi-core.css";
import "../vendor/nibi/dist/web/fonts-ja.css";
import "./nibi.css";
import "./styles.css";

const root = document.getElementById("root");
if (!root) throw new Error("ABAR deck root is missing");

initializeToken();
const queryClient = new QueryClient({
  defaultOptions: {
    queries: { staleTime: 1000, refetchOnWindowFocus: false },
  },
});
createRoot(root).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <ScreenErrorBoundary><App /></ScreenErrorBoundary>
    </QueryClientProvider>
  </StrictMode>,
);
