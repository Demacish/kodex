import { createFileRoute, Link } from "@tanstack/react-router";
import { Smartphone } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { fetchClient } from "@/api/client";
import { AuthLayout, AuthSecondary, AuthSubmit } from "@/components/auth/AuthLayout";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { useAccount } from "@/lib/account";

interface AppLoginSearch {
  device?: string;
  challenge?: string;
  state?: string;
}

// The only place the code goes: the Kodex app's own address.
const APP_RETURN = "kodex://login";

export const Route = createFileRoute("/_authed/app-login")({
  validateSearch: (search: Record<string, unknown>): AppLoginSearch => ({
    device: typeof search.device === "string" ? search.device.slice(0, 80) : undefined,
    challenge: typeof search.challenge === "string" ? search.challenge : undefined,
    state: typeof search.state === "string" ? search.state.slice(0, 128) : undefined,
  }),
  component: AppLogin,
});

/**
 * The Kodex app logs in through the browser (backend: kodex/core/auth/apps.py):
 * the user, logged in here with any method, lets the app on a device in.
 */
function AppLogin() {
  const { t } = useTranslation();
  const account = useAccount();
  const { device, challenge, state } = Route.useSearch();
  const [error, setError] = useState<string>();
  const [busy, setBusy] = useState(false);
  const valid = !!device && !!challenge && /^[A-Za-z0-9_-]{43,128}$/.test(challenge) && !!state;

  const approve = async () => {
    if (!valid) return;
    setBusy(true);
    const result = await fetchClient.POST("/api/auth/app/approve", { body: { device_name: device, challenge } });
    setBusy(false);
    if (!result.data) return setError(t("appLogin.failed"));
    const query = new URLSearchParams({ code: result.data.code, state });
    window.location.assign(`${APP_RETURN}?${query.toString()}`);
  };

  return (
    <AuthLayout title={t("appLogin.title")} intro={valid ? t("appLogin.intro", { device, name: account.username }) : undefined}>
      {!valid ? (
        <Alert variant="destructive"><AlertDescription>{t("appLogin.invalid")}</AlertDescription></Alert>
      ) : (
        <div className="space-y-5">
          {error && <Alert variant="destructive"><AlertDescription>{error}</AlertDescription></Alert>}
          <p className="flex items-center gap-3 rounded-xl border bg-muted/50 px-4 py-3.5 text-sm font-medium dark:border-white/[0.12] dark:bg-[#1a1e2b]/80">
            <Smartphone className="size-4 shrink-0 text-primary-text" aria-hidden />
            {device}
          </p>
          <p className="text-sm text-muted-foreground dark:text-slate-400">{t("appLogin.what")}</p>
          <AuthSubmit disabled={busy} onClick={() => void approve()}>{t("appLogin.approve")}</AuthSubmit>
          <AuthSecondary render={<Link to="/" />}>{t("common.cancel")}</AuthSecondary>
        </div>
      )}
    </AuthLayout>
  );
}
