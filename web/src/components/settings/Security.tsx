import { useQueryClient } from "@tanstack/react-query";
import { Check, Copy, Download, Fingerprint, KeyRound, Link2, Pencil, ShieldCheck, Trash2 } from "lucide-react";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { api, errorMessage, fetchClient, type Schemas } from "@/api/client";
import { ConfirmDialog } from "@/components/common/ConfirmDialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { format } from "@/i18n";
import { useAccount } from "@/lib/account";
import { addPasskey, passkeysSupported, wasCancelled } from "@/lib/passkeys";
import { deviceName } from "@/readers/device";

import { QrCode } from "./QrCode";
import { Section } from "./Section";

function useRefreshAccount() {
  const queryClient = useQueryClient();
  return () => Promise.all([
    queryClient.invalidateQueries({ queryKey: ["get", "/api/auth/me"] }),
    queryClient.invalidateQueries({ queryKey: ["get", "/api/auth/passkeys"] }),
  ]);
}

/** Passkeys, two-step login and the link to the identity provider. */
export function SecuritySection() {
  const { t } = useTranslation();
  const config = api.useQuery("get", "/api/auth/config");
  return (
    <Section icon={ShieldCheck} title={t("security.title")} description={t("security.intro")}>
      <div className="space-y-6">
        {config.data?.passkeys && <Passkeys />}
        {config.data?.local_login && <TwoStep />}
        {config.data?.oidc && <ProviderLink name={config.data.oidc_name || t("auth.oidcGeneric")} />}
      </div>
    </Section>
  );
}

function Passkeys() {
  const { t } = useTranslation();
  const refresh = useRefreshAccount();
  const passkeys = api.useQuery("get", "/api/auth/passkeys");
  const remove = api.useMutation("delete", "/api/auth/passkeys/{passkey_id}", { onSuccess: () => void refresh() });
  const [adding, setAdding] = useState(false);
  const supported = passkeysSupported();

  const add = async () => {
    setAdding(true);
    try {
      const added = await addPasskey(deviceName());
      toast.success(t("security.passkeys.added", { name: added.name }));
      await refresh();
    } catch (error) {
      if (error instanceof Error && "code" in error && error.code === "ERROR_AUTHENTICATOR_PREVIOUSLY_REGISTERED") toast.error(t("security.passkeys.already"));
      else if (!wasCancelled(error)) toast.error(errorMessage(error, t("security.passkeys.failed")));
    } finally {
      setAdding(false);
    }
  };

  return (
    <div>
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <div>
          <h3 className="flex items-center gap-1.5 text-sm font-semibold"><Fingerprint className="size-4" aria-hidden />{t("security.passkeys.title")}</h3>
          <p className="text-xs text-muted-foreground">{t("security.passkeys.intro")}</p>
        </div>
        <Button size="sm" variant="outline" disabled={!supported || adding} onClick={() => void add()}>{t("security.passkeys.add")}</Button>
      </div>
      {!supported && <p className="text-sm text-muted-foreground">{t("security.passkeys.unsupported")}</p>}
      {passkeys.data && passkeys.data.length > 0 && (
        <ul className="divide-y rounded-lg border" aria-label={t("security.passkeys.title")}>
          {passkeys.data.map((passkey) => (
            <PasskeyRow key={passkey.id} passkey={passkey} onRemove={() => remove.mutateAsync({ params: { path: { passkey_id: passkey.id } } }).catch((error: unknown) => {
              toast.error(errorMessage(error, t("common.errorGeneric")));
            })} />
          ))}
        </ul>
      )}
    </div>
  );
}

function PasskeyRow({ passkey, onRemove }: { passkey: Schemas["PasskeyOut"]; onRemove: () => Promise<unknown> }) {
  const { t } = useTranslation();
  const refresh = useRefreshAccount();
  const [editing, setEditing] = useState(false);
  const rename = api.useMutation("patch", "/api/auth/passkeys/{passkey_id}", { onSuccess: () => void refresh() });
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const name = String(new FormData(event.currentTarget).get("name") ?? "").trim();
    if (name) await rename.mutateAsync({ params: { path: { passkey_id: passkey.id } }, body: { name } });
    setEditing(false);
  };
  return (
    <li className="flex items-center gap-3 px-3 py-2 text-sm">
      <KeyRound className="size-4 shrink-0 text-muted-foreground" aria-hidden />
      {editing ? (
        <form onSubmit={submit} className="flex flex-1 gap-2">
          <Input name="name" defaultValue={passkey.name} maxLength={100} autoFocus aria-label={t("security.passkeys.name")} className="h-8" />
          <Button type="submit" size="sm">{t("common.save")}</Button>
        </form>
      ) : (
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="truncate font-medium">{passkey.name}</span>
            {passkey.backed_up && <Badge variant="secondary">{t("security.passkeys.synced")}</Badge>}
          </div>
          <div className="text-xs text-muted-foreground">
            {t("security.passkeys.addedOn", { when: format.date(passkey.created_at) })} ·{" "}
            {passkey.last_used_at ? t("security.passkeys.used", { when: format.relative(passkey.last_used_at) }) : t("security.passkeys.unused")}
          </div>
        </div>
      )}
      {!editing && (
        <Button variant="ghost" size="icon-sm" aria-label={t("security.passkeys.rename", { name: passkey.name })} onClick={() => setEditing(true)}>
          <Pencil aria-hidden />
        </Button>
      )}
      <ConfirmDialog
        trigger={<Button variant="ghost" size="icon-sm" aria-label={t("security.passkeys.remove", { name: passkey.name })}><Trash2 aria-hidden /></Button>}
        title={t("security.passkeys.remove", { name: passkey.name })}
        description={t("security.passkeys.removeText")}
        confirm={t("security.passkeys.removeShort")}
        onConfirm={onRemove}
      />
    </li>
  );
}

function RecoveryCodes({ codes }: { codes: string[] }) {
  const { t } = useTranslation();
  const [copied, setCopied] = useState(false);
  const text = codes.join("\n");
  const download = () => {
    const url = URL.createObjectURL(new Blob([`${t("security.twoStep.fileHeader", { host: window.location.host })}\n\n${text}\n`], { type: "text/plain" }));
    const link = Object.assign(document.createElement("a"), { href: url, download: "kodex-recovery-codes.txt" });
    link.click();
    URL.revokeObjectURL(url);
  };
  return (
    <div className="space-y-3">
      <ul className="grid grid-cols-2 gap-1.5 rounded-lg border bg-muted/50 p-3 font-mono text-sm" aria-label={t("security.twoStep.codesLabel")}>
        {codes.map((code) => <li key={code}>{code}</li>)}
      </ul>
      <div className="flex gap-2">
        <Button variant="outline" size="sm" onClick={() => void navigator.clipboard.writeText(text).then(() => setCopied(true))}>
          {copied ? <Check aria-hidden /> : <Copy aria-hidden />}
          {copied ? t("common.copied") : t("common.copy")}
        </Button>
        <Button variant="outline" size="sm" onClick={download}><Download aria-hidden />{t("security.twoStep.download")}</Button>
      </div>
    </div>
  );
}

function TwoStep() {
  const { t } = useTranslation();
  const account = useAccount();
  return (
    <div>
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <div>
          <h3 className="flex items-center gap-1.5 text-sm font-semibold">
            <ShieldCheck className="size-4" aria-hidden />
            {t("security.twoStep.title")}
            <Badge variant={account.two_factor ? "default" : "outline"}>{account.two_factor ? t("security.on") : t("security.off")}</Badge>
          </h3>
          <p className="text-xs text-muted-foreground">{t("security.twoStep.intro")}</p>
        </div>
        {account.two_factor ? (
          <div className="flex gap-2">
            <CodeDialog kind="codes" />
            <CodeDialog kind="disable" />
          </div>
        ) : (
          <TotpSetup />
        )}
      </div>
      {account.two_factor && (
        <p className={account.recovery_codes_left <= 3 ? "text-sm text-destructive" : "text-sm text-muted-foreground"}>
          {t("security.twoStep.codesLeft", { count: account.recovery_codes_left })}
        </p>
      )}
    </div>
  );
}

function TotpSetup() {
  const { t } = useTranslation();
  const refresh = useRefreshAccount();
  const [open, setOpen] = useState(false);
  const [setup, setSetup] = useState<Schemas["TotpSetupOut"]>();
  const [codes, setCodes] = useState<string[]>();
  const [error, setError] = useState<string>();

  const begin = async (next: boolean) => {
    setOpen(next);
    setError(undefined);
    if (!next) {
      if (codes) await refresh();
      setSetup(undefined);
      setCodes(undefined);
      return;
    }
    const started = await fetchClient.POST("/api/auth/totp");
    if (started.data) setSetup(started.data);
    else setError(errorMessage(started.error, t("common.errorGeneric")));
  };
  const confirm = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const code = String(new FormData(event.currentTarget).get("code") ?? "");
    const confirmed = await fetchClient.POST("/api/auth/totp/confirm", { body: { code } });
    if (confirmed.data) setCodes(confirmed.data.codes);
    else setError(t("auth.secondStep.wrong"));
  };

  return (
    <Dialog open={open} onOpenChange={(next) => void begin(next)}>
      <DialogTrigger render={<Button size="sm" variant="outline" />}>{t("security.twoStep.turnOn")}</DialogTrigger>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{codes ? t("security.twoStep.codesTitle") : t("security.twoStep.setupTitle")}</DialogTitle>
          <DialogDescription>{codes ? t("security.twoStep.codesIntro") : t("security.twoStep.setupIntro")}</DialogDescription>
        </DialogHeader>
        {codes ? (
          <RecoveryCodes codes={codes} />
        ) : setup ? (
          <form onSubmit={confirm} className="grid gap-4">
            <div className="flex flex-col items-center gap-3">
              <QrCode value={setup.uri} label={t("security.twoStep.qr")} />
              <details className="w-full text-sm">
                <summary className="cursor-pointer text-muted-foreground">{t("security.twoStep.manual")}</summary>
                <code className="mt-2 block break-all rounded bg-muted px-2 py-1.5 font-mono text-xs">{setup.secret}</code>
              </details>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="totp-code">{t("auth.secondStep.codeLabel")}</Label>
              <Input id="totp-code" name="code" inputMode="numeric" autoComplete="one-time-code" pattern="[0-9 ]{6,7}" required />
              {error && <p className="text-sm text-destructive">{error}</p>}
            </div>
            <DialogFooter>
              <Button type="submit">{t("security.twoStep.confirm")}</Button>
            </DialogFooter>
          </form>
        ) : (
          error && <p className="text-sm text-destructive">{error}</p>
        )}
        {codes && (
          <DialogFooter>
            <Button onClick={() => void begin(false)}>{t("security.twoStep.done")}</Button>
          </DialogFooter>
        )}
      </DialogContent>
    </Dialog>
  );
}

/** New recovery codes, or two-step login off: either needs a current code. */
function CodeDialog({ kind }: { kind: "codes" | "disable" }) {
  const { t } = useTranslation();
  const refresh = useRefreshAccount();
  const [open, setOpen] = useState(false);
  const [codes, setCodes] = useState<string[]>();
  const [error, setError] = useState<string>();
  const change = async (next: boolean) => {
    setOpen(next);
    setError(undefined);
    if (!next) {
      setCodes(undefined);
      await refresh();
    }
  };
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const code = String(new FormData(event.currentTarget).get("code") ?? "");
    if (kind === "codes") {
      const made = await fetchClient.POST("/api/auth/recovery-codes", { body: { code } });
      if (made.data) return setCodes(made.data.codes);
    } else {
      const off = await fetchClient.POST("/api/auth/totp/disable", { body: { code } });
      if (off.response.ok) {
        toast.success(t("security.twoStep.turnedOff"));
        return change(false);
      }
    }
    setError(t("auth.secondStep.wrong"));
  };
  return (
    <Dialog open={open} onOpenChange={(next) => void change(next)}>
      <DialogTrigger render={<Button size="sm" variant={kind === "disable" ? "ghost" : "outline"} />}>
        {kind === "codes" ? t("security.twoStep.newCodes") : t("security.twoStep.turnOff")}
      </DialogTrigger>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{kind === "codes" ? (codes ? t("security.twoStep.codesTitle") : t("security.twoStep.newCodes")) : t("security.twoStep.turnOffTitle")}</DialogTitle>
          <DialogDescription>{codes ? t("security.twoStep.codesIntro") : t("security.twoStep.codeNeeded")}</DialogDescription>
        </DialogHeader>
        {codes ? (
          <>
            <RecoveryCodes codes={codes} />
            <DialogFooter><Button onClick={() => void change(false)}>{t("security.twoStep.done")}</Button></DialogFooter>
          </>
        ) : (
          <form onSubmit={submit} className="grid gap-4">
            <div className="space-y-1.5">
              <Label htmlFor={`code-${kind}`}>{t("security.twoStep.codeOrRecovery")}</Label>
              <Input id={`code-${kind}`} name="code" autoComplete="one-time-code" required />
              {error && <p className="text-sm text-destructive">{error}</p>}
            </div>
            <DialogFooter>
              <Button type="submit" variant={kind === "disable" ? "destructive" : "default"}>
                {kind === "codes" ? t("security.twoStep.makeCodes") : t("security.twoStep.turnOff")}
              </Button>
            </DialogFooter>
          </form>
        )}
      </DialogContent>
    </Dialog>
  );
}

function ProviderLink({ name }: { name: string }) {
  const { t } = useTranslation();
  const account = useAccount();
  const refresh = useRefreshAccount();
  const unlink = api.useMutation("delete", "/api/auth/oidc/link", { onSuccess: () => void refresh() });
  const link = async () => {
    const started = await fetchClient.POST("/api/auth/oidc/link");
    if (started.data) window.location.assign(started.data.url);
    else toast.error(errorMessage(started.error, t("common.errorGeneric")));
  };
  return (
    <div className="flex flex-wrap items-center justify-between gap-2">
      <div>
        <h3 className="flex items-center gap-1.5 text-sm font-semibold"><Link2 className="size-4" aria-hidden />{t("security.provider.title", { name })}</h3>
        <p className="text-xs text-muted-foreground">
          {account.oidc ? t("security.provider.linked", { name }) : t("security.provider.intro", { name })}
        </p>
      </div>
      {account.oidc ? (
        <ConfirmDialog
          trigger={<Button size="sm" variant="ghost">{t("security.provider.unlink")}</Button>}
          title={t("security.provider.unlinkTitle", { name })}
          description={t("security.provider.unlinkText", { name })}
          confirm={t("security.provider.unlink")}
          onConfirm={() => unlink.mutateAsync({}).catch((error: unknown) => {
            toast.error(errorMessage(error, t("common.errorGeneric")));
          })}
        />
      ) : (
        <Button size="sm" variant="outline" onClick={() => void link()}>{t("security.provider.link", { name })}</Button>
      )}
    </div>
  );
}
