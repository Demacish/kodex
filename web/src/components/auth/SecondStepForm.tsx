import { Fingerprint } from "lucide-react";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import { fetchClient, type Schemas } from "@/api/client";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import type { Account } from "@/lib/account";
import { loginWithPasskey, passkeysSupported, wasCancelled } from "@/lib/passkeys";

import { AuthField, AuthInput, AuthSecondary, AuthSubmit, OrDivider } from "./AuthLayout";

const EXPIRED = "The login took too long; start again";

/**
 * The second step of a password login: the authenticator app's code, a
 * recovery code, or one of the account's passkeys.
 */
export function SecondStepForm({ step, remember = true, onDone, onRestart }: { step: Schemas["SecondStepOut"]; remember?: boolean; onDone: (account: Account) => void; onRestart: () => void }) {
  const { t } = useTranslation();
  const [recovery, setRecovery] = useState(false);
  const [error, setError] = useState<string>();
  const [expired, setExpired] = useState(false);
  const [busy, setBusy] = useState(false);
  const passkey = step.methods.includes("passkey") && passkeysSupported();

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const code = String(new FormData(event.currentTarget).get("code") ?? "");
    setBusy(true);
    setError(undefined);
    const result = await fetchClient.POST("/api/auth/login/second-step", { body: { ticket: step.ticket, code } });
    setBusy(false);
    if (result.data) return onDone(result.data);
    const status = result.response.status;
    if (status === 429) setError(t("auth.throttled", { seconds: result.response.headers.get("retry-after") ?? "60" }));
    else if (status === 403) setError(t("auth.disabled"));
    else if ((result.error as { detail?: string } | undefined)?.detail === EXPIRED) setExpired(true);
    else setError(t(recovery ? "auth.secondStep.wrongRecovery" : "auth.secondStep.wrong"));
  };

  const withPasskey = async () => {
    setError(undefined);
    try {
      onDone(await loginWithPasskey({ ticket: step.ticket, remember }));
    } catch (failure) {
      if (!wasCancelled(failure)) setError(t("auth.passkeyFailed"));
    }
  };

  if (expired) {
    return (
      <div className="space-y-5">
        <Alert variant="destructive">
          <AlertDescription>{t("auth.secondStep.expired")}</AlertDescription>
        </Alert>
        <AuthSubmit onClick={onRestart}>{t("auth.secondStep.restart")}</AuthSubmit>
      </div>
    );
  }

  return (
    <div className="space-y-5">
      {error && (
        <Alert variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}
      <form className="space-y-5" onSubmit={submit}>
        <AuthField
          id="code"
          label={recovery ? t("auth.secondStep.recoveryLabel") : t("auth.secondStep.codeLabel")}
          hint={recovery ? t("auth.secondStep.recoveryHint") : t("auth.secondStep.codeHint")}
        >
          <AuthInput
            key={recovery ? "recovery" : "code"}
            id="code"
            name="code"
            required
            autoFocus
            autoComplete={recovery ? "off" : "one-time-code"}
            inputMode={recovery ? "text" : "numeric"}
            pattern={recovery ? undefined : "[0-9 ]{6,7}"}
            placeholder={recovery ? "xxxxx-xxxxx" : "123 456"}
            aria-describedby="code-hint"
            className="font-mono tracking-widest"
          />
        </AuthField>
        <AuthSubmit type="submit" disabled={busy}>
          {busy ? t("auth.loggingIn") : t("auth.secondStep.submit")}
        </AuthSubmit>
      </form>
      <Button variant="link" size="sm" className="h-auto w-full p-0" onClick={() => setRecovery(!recovery)}>
        {recovery ? t("auth.secondStep.useApp") : t("auth.secondStep.useRecovery")}
      </Button>
      {passkey && (
        <>
          <OrDivider label={t("auth.or")} />
          <AuthSecondary onClick={() => void withPasskey()}>
            <Fingerprint aria-hidden />
            {t("auth.secondStep.usePasskey")}
          </AuthSecondary>
        </>
      )}
    </div>
  );
}
