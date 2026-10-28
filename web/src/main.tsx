import "./index.css";
import "./i18n";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createRouter, RouterProvider } from "@tanstack/react-router";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { setUnauthorizedHandler } from "@/api/client";
import { ThemeProvider } from "@/lib/theme";

import { routeTree } from "./routeTree.gen";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { staleTime: 30_000, retry: (count, error) => count < 2 && !(error && typeof error === "object" && "detail" in error) },
  },
});

const router = createRouter({
  routeTree,
  context: { queryClient },
  defaultPreload: "intent",
  defaultPreloadStaleTime: 0,
  scrollRestoration: true,
});

declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router;
  }
}

setUnauthorizedHandler(() => {
  queryClient.removeQueries({ queryKey: ["get", "/api/auth/me"] });
  const next = window.location.pathname + window.location.search;
  if (!window.location.pathname.startsWith("/login")) void router.navigate({ to: "/login", search: { next } });
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ThemeProvider>
      <QueryClientProvider client={queryClient}>
        <RouterProvider router={router} />
      </QueryClientProvider>
    </ThemeProvider>
  </StrictMode>,
);

// The service worker (vite-plugin-pwa): only in a built app, never in development.
if (import.meta.env.PROD && "serviceWorker" in navigator) {
  void import("virtual:pwa-register").then(({ registerSW }) => registerSW({ immediate: true }));
  // A client kept from before the server's upgrade updates itself.
  void import("@/lib/stale").then(({ reloadIfStale }) => reloadIfStale());
}
