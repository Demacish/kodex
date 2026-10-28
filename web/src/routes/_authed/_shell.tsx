import { createFileRoute, Outlet } from "@tanstack/react-router";

import { AppShell } from "@/components/shell/AppShell";

/** The pages with the app's navigation (the readers have none). */
export const Route = createFileRoute("/_authed/_shell")({
  component: () => (
    <AppShell>
      <Outlet />
    </AppShell>
  ),
});
