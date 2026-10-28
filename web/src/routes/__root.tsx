import type { QueryClient } from "@tanstack/react-query";
import { createRootRouteWithContext, Link, Outlet, type ErrorComponentProps } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";

import { ErrorState } from "@/components/common/states";
import { Button } from "@/components/ui/button";
import { Toaster } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";

export interface RouterContext {
  queryClient: QueryClient;
}

export const Route = createRootRouteWithContext<RouterContext>()({
  component: Root,
  notFoundComponent: NotFound,
  errorComponent: RootError,
});

function Root() {
  return (
    <TooltipProvider>
      <Outlet />
      <Toaster position="bottom-center" />
    </TooltipProvider>
  );
}

export function NotFound() {
  const { t } = useTranslation();
  return (
    <div className="mx-auto flex min-h-[60dvh] max-w-md flex-col items-center justify-center gap-3 px-4 text-center">
      <p className="text-5xl font-bold text-primary-text">404</p>
      <h1 className="text-xl font-semibold">{t("common.notFoundTitle")}</h1>
      <p className="text-sm text-muted-foreground">{t("common.notFoundText")}</p>
      <Button render={<Link to="/" />}>{t("common.toHome")}</Button>
    </div>
  );
}

function RootError({ error, reset }: ErrorComponentProps) {
  return (
    <div className="mx-auto max-w-lg px-4 py-16">
      <ErrorState error={error} onRetry={reset} />
    </div>
  );
}
