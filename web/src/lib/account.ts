import { useQueryClient } from "@tanstack/react-query";

import { api, fetchClient, type Schemas } from "@/api/client";

export type Account = Schemas["AccountOut"];

/** Only paths on this site, so a link can't send someone elsewhere after login. */
export function safeNext(next: string | undefined): string {
  return next && next.startsWith("/") && !next.startsWith("//") && !next.startsWith("/login") ? next : "/";
}

export const accountQuery = api.queryOptions("get", "/api/auth/me", {}, { staleTime: 5 * 60_000, retry: false });

/** The logged-in account; the _authed layout has loaded it already. */
export function useAccount(): Account {
  const { data } = api.useQuery("get", "/api/auth/me", {}, { staleTime: 5 * 60_000, retry: false });
  if (!data) throw new Error("useAccount outside the logged-in pages");
  return data;
}

export function useLogout() {
  const queryClient = useQueryClient();
  return async () => {
    await fetchClient.POST("/api/auth/logout");
    queryClient.clear();
    // What the service worker kept is this user's: gone on a shared device.
    if ("caches" in window) {
      for (const name of ["api", "covers", "pages"]) await caches.delete(name).catch(() => false);
    }
    window.location.assign("/login");
  };
}
