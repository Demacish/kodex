import { createFileRoute, Outlet, redirect } from "@tanstack/react-router";

import { accountQuery } from "@/lib/account";

/** Every page behind the login. */
export const Route = createFileRoute("/_authed")({
  beforeLoad: async ({ context, location }) => {
    const account = await context.queryClient.ensureQueryData(accountQuery).catch(() => undefined);
    if (!account) throw redirect({ to: "/login", search: { next: location.href } });
    return { account };
  },
  component: Outlet,
});
