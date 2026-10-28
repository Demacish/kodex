/**
 * The service worker serves the client it has until a new one is installed,
 * so right after the server is upgraded a page can still be the old client,
 * which may not know what the new server asks for (a setup code, say). When
 * the server's version isn't this build's, the worker is told to update;
 * vite-plugin-pwa reloads the page once the new client takes over, and if it
 * hasn't after a while, the page reloads anyway. Once per version.
 */
export async function reloadIfStale(): Promise<void> {
  const response = await fetch("/api/auth/config", { cache: "no-store" }).catch(() => undefined);
  if (!response?.ok) return;
  const { version } = (await response.json()) as { version?: string };
  if (!version || version === __KODEX_VERSION__) return;
  const key = `kodex-reloaded-for-${version}`;
  try {
    if (sessionStorage.getItem(key)) return;
    sessionStorage.setItem(key, "1");
  } catch {
    return;
  }
  const registration = await navigator.serviceWorker?.getRegistration().catch(() => undefined);
  await registration?.update().catch(() => undefined);
  window.setTimeout(() => window.location.reload(), registration ? 15_000 : 0);
}
