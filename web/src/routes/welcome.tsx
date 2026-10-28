import { useQueryClient } from "@tanstack/react-query";
import { createFileRoute, Link, useNavigate } from "@tanstack/react-router";
import { useEffect, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import { fetchClient, type Schemas } from "@/api/client";
import { AuthField, AuthLayout, AuthSubmit, PasswordInput } from "@/components/auth/AuthLayout";
import { SecondStepForm } from "@/components/auth/SecondStepForm";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Skeleton } from "@/components/ui/skeleton";
import { accountQuery, type Account } from "@/lib/account";

export const Route = createFileRoute("/welcome")({
  component: Welcome,
});

/** The token travels after the #, so it never reaches a server log. */
function linkToken(): string {
  return decodeURIComponent(window.location.hash.slice(1));
}

/** A sign-in link from an admin: the user chooses a password and is in. */
function Welcome() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [token] = useState(linkToken);
  const [username, setUsername] = useState<string | null>();
  const [error, setError] = useState<string>();
  const [busy, setBusy] = useState(false);
  const [secondStep, setSecondStep] = useState<Schemas["SecondStepOut"]>();

  useEffect(() => {
    if (!token) return setUsername(null);
    window.history.replaceState(window.history.state, "", window.location.pathname);
    void fetchClient.POST("/api/auth/sign-in-link/check", { body: { token } }).then((result) => setUsername(result.data?.username ?? null));
  }, [token]);

  const finish = async (account: Account) => {
    queryClient.setQueryData(accountQuery.queryKey, account);
    await navigate({ to: "/settings", replace: true });
  };

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const password = String(form.get("password") ?? "");
    if (password !== form.get("again")) return setError(t("settings.passwordsDiffer"));
    setBusy(true);
    setError(undefined);
    const result = await fetchClient.POST("/api/auth/sign-in-link", { body: { token, password } });
    setBusy(false);
    if (result.data?.second_step) return setSecondStep(result.data.second_step);
    if (result.data?.account) return finish(result.data.account);
    const status = result.response.status;
    if (status === 422) setError(t("auth.passwordHint"));
    else if (status === 404) setUsername(null);
    else setError(t("common.errorGeneric"));
  };

  if (secondStep) {
    return (
      <AuthLayout title={t("auth.secondStep.title")} intro={t("auth.secondStep.intro")}>
        <SecondStepForm step={secondStep} onDone={(account) => void finish(account)} onRestart={() => void navigate({ to: "/login" })} />
      </AuthLayout>
    );
  }
  if (username === null) {
    return (
      <AuthLayout title={t("welcome.invalidTitle")} intro={t("welcome.invalidIntro")}>
        <AuthSubmit render={<Link to="/login" />}>{t("auth.login")}</AuthSubmit>
      </AuthLayout>
    );
  }
  return (
    <AuthLayout title={username ? t("welcome.title", { name: username }) : t("welcome.titleShort")} intro={t("welcome.intro")}>
      {error && (
        <Alert variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}
      {username === undefined ? (
        <Skeleton className="h-40 w-full rounded-xl" />
      ) : (
        <form className="space-y-5" onSubmit={submit}>
          <input type="text" name="username" autoComplete="username" value={username} readOnly hidden />
          <AuthField id="password" label={t("settings.newPassword")} hint={t("auth.passwordHint")}>
            <PasswordInput id="password" name="password" autoComplete="new-password" minLength={8} required autoFocus aria-describedby="password-hint" />
          </AuthField>
          <AuthField id="again" label={t("settings.againPassword")}>
            <PasswordInput id="again" name="again" autoComplete="new-password" minLength={8} required />
          </AuthField>
          <AuthSubmit type="submit" disabled={busy}>
            {t("welcome.submit")}
          </AuthSubmit>
        </form>
      )}
    </AuthLayout>
  );
}
