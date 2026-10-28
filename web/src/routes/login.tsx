import { useQueryClient } from "@tanstack/react-query";
import { createFileRoute, redirect, useNavigate } from "@tanstack/react-router";
import { Fingerprint, KeyRound } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import { api, fetchClient, type Schemas } from "@/api/client";
import { AuthLayout, OrDivider } from "@/components/auth/AuthLayout";
import { SecondStepForm } from "@/components/auth/SecondStepForm";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { accountQuery, safeNext, type Account } from "@/lib/account";
import { browserSupportsWebAuthnAutofill, cancelPasskeyPrompt, loginWithPasskey, passkeysSupported, wasCancelled } from "@/lib/passkeys";

interface LoginSearch {
  next?: string;
  error?: string;
}

export const Route = createFileRoute("/login")({
  validateSearch: (search: Record<string, unknown>): LoginSearch => ({
    next: typeof search.next === "string" ? search.next : undefined,
    error: typeof search.error === "string" ? search.error : undefined,
  }),
  beforeLoad: async ({ context, search }) => {
    const account = await context.queryClient.fetchQuery(accountQuery).catch(() => undefined);
    if (account) throw redirect({ href: safeNext(search.next) });
  },
  component: LoginPage,
});

function LoginPage() {
  const { t } = useTranslation();
  const search = Route.useSearch();
  const config = api.useQuery("get", "/api/auth/config");
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [error, setError] = useState<string | undefined>(search.error);
  const [busy, setBusy] = useState(false);
  const [secondStep, setSecondStep] = useState<Schemas["SecondStepOut"]>();
  const setup = config.data?.setup_required ?? false;
  const passkeys = (config.data?.passkeys ?? false) && !setup && passkeysSupported();

  const finish = async (account: Account) => {
    cancelPasskeyPrompt();
    queryClient.setQueryData(accountQuery.queryKey, account);
    await navigate({ href: safeNext(search.next), replace: true });
  };

  // A passkey offered among the username field's suggestions, where the
  // browser or password manager can.
  useEffect(() => {
    if (!passkeys || secondStep) return;
    let active = true;
    void browserSupportsWebAuthnAutofill().then((supported) => {
      if (!supported || !active) return;
      loginWithPasskey({ autofill: true }).then(finish, (failure: unknown) => {
        if (active && !wasCancelled(failure)) setError(t("auth.passkeyFailed"));
      });
    });
    return () => {
      active = false;
      cancelPasskeyPrompt();
    };
    // Once per form: finish and t don't change what is asked for.
  }, [passkeys, secondStep]); // eslint-disable-line react-hooks/exhaustive-deps

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const username = String(form.get("username") ?? "");
    const password = String(form.get("password") ?? "");
    setBusy(true);
    setError(undefined);
    let response: Response;
    if (setup) {
      const result = await fetchClient.POST("/api/auth/setup", {
        body: { username, password, email: String(form.get("email") ?? "") || null },
      });
      setBusy(false);
      if (result.data) return finish(result.data);
      response = result.response;
    } else {
      const result = await fetchClient.POST("/api/auth/login", { body: { username, password } });
      setBusy(false);
      if (result.data?.second_step) return setSecondStep(result.data.second_step);
      if (result.data?.account) return finish(result.data.account);
      response = result.response;
    }
    const status = response.status;
    if (status === 429) setError(t("auth.throttled", { seconds: response.headers.get("retry-after") ?? "60" }));
    else if (status === 403) setError(t(config.data?.local_login === false ? "auth.localOff" : "auth.disabled"));
    else if (status === 422 && setup) setError(t("auth.passwordHint"));
    else setError(t("auth.wrong"));
  };

  const passkeyLogin = async () => {
    setError(undefined);
    try {
      await finish(await loginWithPasskey());
    } catch (failure) {
      if (!wasCancelled(failure)) setError(t("auth.passkeyFailed"));
    }
  };

  const oidcName = config.data?.oidc_name || t("auth.oidcGeneric");
  const oidcHref = `/api/auth/oidc/login?next=${encodeURIComponent(safeNext(search.next))}`;

  if (secondStep) {
    return (
      <AuthLayout title={t("auth.secondStep.title")} intro={t("auth.secondStep.intro")}>
        <SecondStepForm step={secondStep} onDone={(account) => void finish(account)} onRestart={() => setSecondStep(undefined)} />
      </AuthLayout>
    );
  }

  return (
    <AuthLayout title={setup ? t("auth.setupTitle") : t("auth.loginTitle")} intro={setup ? t("auth.setupIntro") : t("auth.loginIntro")}>
      {error && (
        <Alert variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}
      {config.isPending ? (
        <div className="space-y-3">
          <Skeleton className="h-9 w-full" />
          <Skeleton className="h-9 w-full" />
        </div>
      ) : (
        <>
          {(config.data?.local_login || setup) && (
            <form className="space-y-4" onSubmit={submit}>
              <div className="space-y-1.5">
                <Label htmlFor="username">{t("auth.username")}</Label>
                <Input id="username" name="username" autoComplete={passkeys ? "username webauthn" : "username"} required autoFocus />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="password">{t("auth.password")}</Label>
                <Input
                  id="password"
                  name="password"
                  type="password"
                  autoComplete={setup ? "new-password" : "current-password"}
                  minLength={setup ? 8 : undefined}
                  required
                  aria-describedby={setup ? "password-hint" : undefined}
                />
                {setup && (
                  <p id="password-hint" className="text-xs text-muted-foreground">
                    {t("auth.passwordHint")}
                  </p>
                )}
              </div>
              {setup && (
                <div className="space-y-1.5">
                  <Label htmlFor="email">{t("auth.email")}</Label>
                  <Input id="email" name="email" type="email" autoComplete="email" />
                </div>
              )}
              <Button type="submit" className="w-full" disabled={busy}>
                {busy ? t("auth.loggingIn") : setup ? t("auth.setupSubmit") : t("auth.login")}
              </Button>
            </form>
          )}
          {(passkeys || (config.data?.oidc && !setup)) && config.data?.local_login && <OrDivider label={t("auth.or")} />}
          {passkeys && (
            <Button variant="outline" className="w-full" onClick={() => void passkeyLogin()}>
              <Fingerprint aria-hidden />
              {t("auth.passkeyLogin")}
            </Button>
          )}
          {config.data?.oidc && !setup && (
            <Button variant="outline" className="w-full" render={<a href={oidcHref} />}>
              <KeyRound aria-hidden />
              {t("auth.oidc", { name: oidcName })}
            </Button>
          )}
          {config.data && !config.data.local_login && !config.data.oidc && !setup && (
            <p className="text-sm text-muted-foreground">{t("auth.noMethod")}</p>
          )}
        </>
      )}
    </AuthLayout>
  );
}
