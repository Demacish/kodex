import { useQueryClient } from "@tanstack/react-query";
import { createFileRoute, redirect, useNavigate } from "@tanstack/react-router";
import { Fingerprint, KeyRound } from "lucide-react";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import { api, fetchClient, type Schemas } from "@/api/client";
import { AuthField, AuthInput, AuthLayout, AuthSecondary, AuthSubmit, OrDivider, PasswordInput } from "@/components/auth/AuthLayout";
import { SecondStepForm } from "@/components/auth/SecondStepForm";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Checkbox } from "@/components/ui/checkbox";
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
  // "Remember me on this device": without it the login ends with the browser.
  const [remember, setRemember] = useState(true);
  const rememberNow = useRef(remember);
  useEffect(() => {
    rememberNow.current = remember;
  }, [remember]);
  const [forgotShown, setForgotShown] = useState(false);
  const setup = config.data?.setup_required ?? false;
  // The server has accounts (from v1, say) but no admin who can log in.
  const claim = setup && (config.data?.setup_code_required ?? false);
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
      // Nobody asked for this one, so a failure (no passkey on the device,
      // a browser that can't) says nothing; the button below reports its own.
      loginWithPasskey({ autofill: true, remember: () => rememberNow.current }).then(finish, () => undefined);
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
        body: { username, password, remember, email: String(form.get("email") ?? "") || null, code: claim ? String(form.get("code") ?? "") : null },
      });
      setBusy(false);
      if (result.data) return finish(result.data);
      response = result.response;
    } else {
      const result = await fetchClient.POST("/api/auth/login", { body: { username, password, remember } });
      setBusy(false);
      if (result.data?.second_step) return setSecondStep(result.data.second_step);
      if (result.data?.account) return finish(result.data.account);
      response = result.response;
    }
    const status = response.status;
    if (status === 429) setError(t("auth.throttled", { seconds: response.headers.get("retry-after") ?? "60" }));
    else if (status === 403 && claim) setError(t("auth.setupWrongCode"));
    else if (status === 409 && setup) setError(t("auth.setupTaken"));
    else if (status === 403) setError(t(config.data?.local_login === false ? "auth.localOff" : "auth.disabled"));
    else if (status === 422 && setup) setError(t("auth.passwordHint"));
    else setError(t("auth.wrong"));
  };

  const passkeyLogin = async () => {
    setError(undefined);
    try {
      await finish(await loginWithPasskey({ remember }));
    } catch (failure) {
      if (!wasCancelled(failure)) setError(t("auth.passkeyFailed"));
    }
  };

  const oidcName = config.data?.oidc_name || t("auth.oidcGeneric");
  const oidcHref = `/api/auth/oidc/login?next=${encodeURIComponent(safeNext(search.next))}`;

  if (secondStep) {
    return (
      <AuthLayout title={t("auth.secondStep.title")} intro={t("auth.secondStep.intro")}>
        <SecondStepForm step={secondStep} remember={remember} onDone={(account) => void finish(account)} onRestart={() => setSecondStep(undefined)} />
      </AuthLayout>
    );
  }

  return (
    <AuthLayout
      title={setup ? t("auth.setupTitle") : t("auth.loginTitle")}
      intro={claim ? t("auth.setupClaimIntro") : setup ? t("auth.setupIntro") : t("auth.loginIntro")}
      footer={setup ? undefined : t("auth.noAccount")}
    >
      {error && (
        <Alert variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}
      {config.isPending ? (
        <div className="space-y-4">
          <Skeleton className="h-12 w-full rounded-xl" />
          <Skeleton className="h-12 w-full rounded-xl" />
          <Skeleton className="h-12 w-full rounded-xl" />
        </div>
      ) : (
        <>
          {(config.data?.local_login || setup) && (
            <form className="space-y-5" onSubmit={submit}>
              {claim && (
                <AuthField id="code" label={t("auth.setupCode")} hint={t("auth.setupCodeHint")}>
                  <AuthInput
                    id="code"
                    name="code"
                    autoComplete="one-time-code"
                    autoCapitalize="characters"
                    spellCheck={false}
                    placeholder="ABCD-EFGH"
                    required
                    autoFocus
                    aria-describedby="code-hint"
                    className="font-mono tracking-widest uppercase"
                  />
                </AuthField>
              )}
              <AuthField id="username" label={t("auth.username")}>
                <AuthInput
                  id="username"
                  name="username"
                  autoComplete={passkeys ? "username webauthn" : "username"}
                  placeholder={t("auth.usernamePlaceholder")}
                  required
                  autoFocus={!claim}
                />
              </AuthField>
              <AuthField
                id="password"
                label={t("auth.password")}
                hint={setup ? t("auth.passwordHint") : undefined}
                aside={
                  !setup && (
                    <button
                      type="button"
                      aria-expanded={forgotShown}
                      aria-controls="forgot"
                      onClick={() => setForgotShown((shown) => !shown)}
                      className="rounded text-sm font-medium text-primary-text sm:text-xs transition-colors outline-none hover:underline focus-visible:ring-2 focus-visible:ring-primary/40"
                    >
                      {t("auth.forgot")}
                    </button>
                  )
                }
              >
                <PasswordInput
                  id="password"
                  name="password"
                  autoComplete={setup ? "new-password" : "current-password"}
                  minLength={setup ? 8 : undefined}
                  placeholder="••••••••••••"
                  required
                  aria-describedby={setup ? "password-hint" : forgotShown ? "forgot" : undefined}
                />
              </AuthField>
              {!setup && forgotShown && (
                <p id="forgot" role="status" className="-mt-2 rounded-xl bg-muted/60 px-3.5 py-2.5 text-[13px] text-muted-foreground sm:text-xs dark:bg-[#1a1e2b]/70 dark:text-slate-300">
                  {t("auth.forgotHint")}
                </p>
              )}
              {setup && (
                <AuthField id="email" label={t("auth.email")}>
                  <AuthInput id="email" name="email" type="email" autoComplete="email" />
                </AuthField>
              )}
              {!setup && (
                <label className="flex w-fit cursor-pointer items-center gap-3 py-1 text-sm text-muted-foreground select-none sm:gap-2.5 sm:py-0 sm:text-xs dark:text-slate-400">
                  <Checkbox className="size-5 sm:size-4" checked={remember} onCheckedChange={(checked) => setRemember(checked === true)} aria-label={t("auth.remember")} />
                  {t("auth.remember")}
                </label>
              )}
              <AuthSubmit type="submit" disabled={busy}>
                {busy ? t("auth.loggingIn") : claim ? t("auth.setupClaimSubmit") : setup ? t("auth.setupSubmit") : t("auth.login")}
              </AuthSubmit>
            </form>
          )}
          {(passkeys || (config.data?.oidc && !setup)) && config.data?.local_login && <OrDivider label={t("auth.or")} />}
          {passkeys && (
            <AuthSecondary onClick={() => void passkeyLogin()}>
              <Fingerprint aria-hidden />
              {t("auth.passkeyLogin")}
            </AuthSecondary>
          )}
          {config.data?.oidc && !setup && (
            <AuthSecondary render={<a href={oidcHref} />}>
              <KeyRound aria-hidden />
              {t("auth.oidc", { name: oidcName })}
            </AuthSecondary>
          )}
          {config.data && !config.data.local_login && !config.data.oidc && !setup && (
            <p className="text-sm text-muted-foreground">{t("auth.noMethod")}</p>
          )}
        </>
      )}
    </AuthLayout>
  );
}
