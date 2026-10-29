import { useQueryClient } from "@tanstack/react-query";
import { createFileRoute } from "@tanstack/react-router";
import { ArrowDown, ArrowUp, Bell, Check, Copy, KeyRound, LayoutGrid, MonitorSmartphone, Palette, Rss, Send, ShieldCheck, Tablet, Trash2 } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { api, errorMessage, type Schemas } from "@/api/client";
import { ConfirmDialog } from "@/components/common/ConfirmDialog";
import { PageHeader } from "@/components/common/states";
import { Section } from "@/components/settings/Section";
import { KoboDevices, koboEndpoint } from "@/components/settings/KoboDevices";
import { SecuritySection } from "@/components/settings/Security";
import { TrackersSection } from "@/components/settings/Trackers";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { format, LANGUAGES, setLanguage, type Language } from "@/i18n";
import { useAccount } from "@/lib/account";
import { useTheme, type Theme } from "@/lib/theme";
import { HOME_SECTIONS, type HomeSection } from "@/lib/home";
import { deviceName } from "@/readers/device";

interface SettingsSearch {
  linked?: string;
  link_error?: string;
  tracker?: string;
  tracker_error?: string;
}

export const Route = createFileRoute("/_authed/_shell/settings")({
  validateSearch: (search: Record<string, unknown>): SettingsSearch => ({
    linked: typeof search.linked === "string" || typeof search.linked === "number" ? String(search.linked) : undefined,
    link_error: typeof search.link_error === "string" ? search.link_error : undefined,
    tracker: typeof search.tracker === "string" ? search.tracker : undefined,
    tracker_error: typeof search.tracker_error === "string" ? search.tracker_error : undefined,
  }),
  component: Settings,
});

const TRACKER_NAMES: Record<string, string> = { anilist: "AniList", myanimelist: "MyAnimeList", mangaupdates: "MangaUpdates", kitsu: "Kitsu" };

function Settings() {
  const { t } = useTranslation();
  const account = useAccount();
  const profile = api.useQuery("get", "/api/me");
  const search = Route.useSearch();
  const navigate = Route.useNavigate();
  // Back from linking the account at the identity provider.
  useEffect(() => {
    if (!search.linked && !search.link_error) return;
    if (search.link_error) toast.error(t("security.provider.failed", { reason: search.link_error }));
    else toast.success(t("security.provider.done"));
    void navigate({ search: {}, replace: true });
  }, [search.linked, search.link_error]); // eslint-disable-line react-hooks/exhaustive-deps
  // Back from a tracker's login page (AniList, MyAnimeList).
  useEffect(() => {
    if (!search.tracker && !search.tracker_error) return;
    const name = TRACKER_NAMES[search.tracker ?? search.tracker_error ?? ""] ?? "";
    if (search.tracker_error) toast.error(t("trackers.failed", { name }));
    else toast.success(t("trackers.done", { name }));
    void navigate({ search: {}, hash: "trackers", replace: true });
  }, [search.tracker, search.tracker_error]); // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <div className="max-w-2xl space-y-6">
      <PageHeader title={t("nav.settings")} />
      <AccountSection />
      {account.auth_method === "session" && <SecuritySection />}
      <AppearanceSection />
      {profile.data && <HomeSections profile={profile.data} />}
      {profile.data && <ProfileField profile={profile.data} field="kindle_email" icon={Send} />}
      {profile.data && <ProfileField profile={profile.data} field="ntfy_topic" icon={Bell} />}
      <TrackersSection />
      <KeysSection hasLegacyToken={profile.data?.has_opds_token ?? false} />
    </div>
  );
}

function AccountSection() {
  const { t } = useTranslation();
  const account = useAccount();
  const queryClient = useQueryClient();
  const sessions = api.useQuery("get", "/api/auth/sessions", {}, { enabled: account.auth_method === "session" });
  const end = api.useMutation("delete", "/api/auth/sessions/{session_id}", {
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["get", "/api/auth/sessions"] }),
  });
  const change = api.useMutation("post", "/api/auth/password");
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    if (data.get("new") !== data.get("again")) return void toast.error(t("settings.passwordsDiffer"));
    try {
      await change.mutateAsync({ body: { current_password: String(data.get("current") ?? "") || null, new_password: String(data.get("new")) } });
      toast.success(t("settings.passwordChanged"));
      form.reset();
      await queryClient.invalidateQueries({ queryKey: ["get", "/api/auth/sessions"] });
    } catch (error) {
      toast.error(errorMessage(error, t("common.errorGeneric")));
    }
  };
  return (
    <Section icon={ShieldCheck} title={t("settings.account")} description={t("settings.accountIntro", { name: account.username })}>
      <div className="mb-4 flex flex-wrap gap-2">
        <Badge variant="secondary">{t(`account.roles.${account.role as "admin"}`)}</Badge>
        {account.oidc && <Badge variant="outline">{t("settings.oidcLinked")}</Badge>}
        {account.has_password && <Badge variant="outline">{t("settings.hasPassword")}</Badge>}
        {account.two_factor && <Badge variant="outline">{t("security.twoStep.title")}</Badge>}
        {account.passkeys > 0 && <Badge variant="outline">{t("security.passkeys.count", { count: account.passkeys })}</Badge>}
      </div>
      {account.auth_method === "session" && (
        <>
          <form onSubmit={submit} className="mb-6 grid gap-3 sm:grid-cols-3">
            {account.has_password && (
              <div className="space-y-1.5">
                <Label htmlFor="pw-current">{t("settings.currentPassword")}</Label>
                <Input id="pw-current" name="current" type="password" autoComplete="current-password" required />
              </div>
            )}
            <div className="space-y-1.5">
              <Label htmlFor="pw-new">{account.has_password ? t("settings.newPassword") : t("settings.setPassword")}</Label>
              <Input id="pw-new" name="new" type="password" autoComplete="new-password" minLength={8} required />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="pw-again">{t("settings.againPassword")}</Label>
              <Input id="pw-again" name="again" type="password" autoComplete="new-password" minLength={8} required />
            </div>
            <div className="sm:col-span-3">
              <Button type="submit" size="sm" disabled={change.isPending}>{account.has_password ? t("settings.changePassword") : t("settings.setPassword")}</Button>
            </div>
          </form>
          <h3 className="mb-2 text-sm font-semibold">{t("settings.sessions")}</h3>
          <ul className="divide-y rounded-lg border">
            {(sessions.data ?? []).map((session) => (
              <li key={session.id} className="flex items-center gap-3 px-3 py-2 text-sm">
                <MonitorSmartphone className="size-4 shrink-0 text-muted-foreground" aria-hidden />
                <div className="min-w-0 flex-1">
                  <div className="truncate" title={session.user_agent ?? undefined}>{session.user_agent ? deviceName(session.user_agent) : t("settings.unknownDevice")}</div>
                  <div className="text-xs text-muted-foreground">{t("settings.lastSeen", { when: format.relative(session.last_seen_at) })}</div>
                </div>
                {session.current ? (
                  <Badge variant="secondary">{t("settings.thisDevice")}</Badge>
                ) : (
                  <Button variant="ghost" size="sm" onClick={() => end.mutate({ params: { path: { session_id: session.id } } })}>{t("settings.endSession")}</Button>
                )}
              </li>
            ))}
          </ul>
        </>
      )}
    </Section>
  );
}

function AppearanceSection() {
  const { t, i18n } = useTranslation();
  const { theme, setTheme } = useTheme();
  return (
    <Section icon={Palette} title={t("settings.appearance")}>
      <div className="flex flex-wrap gap-6">
        <div className="space-y-2">
          <div className="text-sm font-medium">{t("theme.label")}</div>
          <ToggleGroup value={[theme]} onValueChange={(v: string[]) => v[0] && setTheme(v[0] as Theme)} variant="outline" size="sm">
            {(["system", "light", "dark"] as const).map((value) => <ToggleGroupItem key={value} value={value}>{t(`theme.${value}`)}</ToggleGroupItem>)}
          </ToggleGroup>
        </div>
        <div className="space-y-2">
          <div className="text-sm font-medium">{t("language.label")}</div>
          <ToggleGroup value={[i18n.language]} onValueChange={(v: string[]) => v[0] && setLanguage(v[0] as Language)} variant="outline" size="sm">
            {LANGUAGES.map((language) => <ToggleGroupItem key={language} value={language} lang={language}>{t(`language.${language}`)}</ToggleGroupItem>)}
          </ToggleGroup>
        </div>
      </div>
    </Section>
  );
}

function useSaveProfile() {
  const queryClient = useQueryClient();
  const save = api.useMutation("put", "/api/me", { onSuccess: (data) => queryClient.setQueryData(["get", "/api/me", {}], data) });
  return save;
}

function HomeSections({ profile }: { profile: Schemas["UserOut"] }) {
  const { t } = useTranslation();
  const save = useSaveProfile();
  const visible = (profile.home_sections as HomeSection[] | null | undefined) ?? [...HOME_SECTIONS];
  const rows = [...visible.map((key) => ({ key, shown: true })), ...HOME_SECTIONS.filter((k) => !visible.includes(k)).map((key) => ({ key, shown: false }))];
  const write = (next: HomeSection[]) => save.mutate({ body: { home_sections: next } });
  const move = (index: number, by: number) => {
    const next = [...visible];
    const [item] = next.splice(index, 1);
    next.splice(index + by, 0, item!);
    write(next);
  };
  return (
    <Section icon={LayoutGrid} title={t("settings.home")} description={t("settings.homeIntro")}>
      <ul className="space-y-1.5">
        {rows.map((row, index) => (
          <li key={row.key} className="flex items-center gap-2 rounded-lg border px-3 py-1.5 text-sm">
            <span className={row.shown ? "flex-1" : "flex-1 text-muted-foreground"}>{t(`home.sections.${row.key}`)}</span>
            {row.shown && (
              <>
                <Button variant="ghost" size="icon-sm" disabled={index === 0} onClick={() => move(index, -1)} aria-label={t("settings.moveUp", { name: t(`home.sections.${row.key}`) })}><ArrowUp aria-hidden /></Button>
                <Button variant="ghost" size="icon-sm" disabled={index === visible.length - 1} onClick={() => move(index, 1)} aria-label={t("settings.moveDown", { name: t(`home.sections.${row.key}`) })}><ArrowDown aria-hidden /></Button>
              </>
            )}
            <Button variant="outline" size="sm" onClick={() => write(row.shown ? visible.filter((k) => k !== row.key) : [...visible, row.key])}>
              {row.shown ? t("settings.hide") : t("settings.show")}
            </Button>
          </li>
        ))}
      </ul>
    </Section>
  );
}

function ProfileField({ profile, field, icon }: { profile: Schemas["UserOut"]; field: "kindle_email" | "ntfy_topic"; icon: typeof Bell }) {
  const { t } = useTranslation();
  const save = useSaveProfile();
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const value = String(new FormData(event.currentTarget).get("value") ?? "").trim();
    try {
      await save.mutateAsync({ body: { [field]: value } });
      toast.success(t("common.saved"));
    } catch {
      toast.error(t(`settings.${field}.invalid`));
    }
  };
  return (
    <Section icon={icon} title={t(`settings.${field}.title`)} description={t(`settings.${field}.intro`)}>
      <form onSubmit={submit} className="flex gap-2">
        <Input name="value" type={field === "kindle_email" ? "email" : "text"} defaultValue={profile[field] ?? ""} placeholder={t(`settings.${field}.placeholder`)} aria-label={t(`settings.${field}.title`)} />
        <Button type="submit" disabled={save.isPending}>{t("common.save")}</Button>
      </form>
    </Section>
  );
}

const PURPOSES = ["opds", "kosync", "app", "kobo"] as const;

function KeysSection({ hasLegacyToken }: { hasLegacyToken: boolean }) {
  const { t } = useTranslation();
  const account = useAccount();
  const queryClient = useQueryClient();
  const keys = api.useQuery("get", "/api/me/api-keys");
  const create = api.useMutation("post", "/api/me/api-keys");
  const remove = api.useMutation("delete", "/api/me/api-keys/{key_id}", {
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["get", "/api/me/api-keys"] }),
  });
  const revokeLegacy = api.useMutation("delete", "/api/me/opds-token", {
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["get", "/api/me"] }),
  });
  const [purpose, setPurpose] = useState<(typeof PURPOSES)[number]>("opds");
  const [shown, setShown] = useState<Schemas["ApiKeyCreated"] | null>(null);
  const [copied, setCopied] = useState(false);
  const origin = window.location.origin;

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = event.currentTarget;
    const name = String(new FormData(form).get("name") ?? "").trim() || t(`settings.keys.purposes.${purpose}`);
    try {
      const created = await create.mutateAsync({ body: { name, purpose } });
      setShown(created);
      setCopied(false);
      form.reset();
      await queryClient.invalidateQueries({ queryKey: ["get", "/api/me/api-keys"] });
      if (created.purpose === "kobo") await queryClient.invalidateQueries({ queryKey: ["get", "/api/me/kobo"] });
    } catch (error) {
      toast.error(errorMessage(error, t("common.errorGeneric")));
    }
  };
  const copy = async (value: string) => {
    await navigator.clipboard.writeText(value);
    setCopied(true);
  };

  return (
    <Section icon={KeyRound} title={t("settings.keys.title")} description={t("settings.keys.intro")}>
      <dl className="mb-5 grid gap-3 text-sm sm:grid-cols-2">
        <div className="rounded-lg border p-3">
          <dt className="flex items-center gap-1.5 font-medium"><Rss className="size-3.5" aria-hidden />{t("settings.keys.opdsTitle")}</dt>
          <dd className="mt-1 text-muted-foreground">{t("settings.keys.opdsHelp")}</dd>
          <dd className="mt-2 flex flex-wrap gap-1.5">
            <code className="rounded bg-muted px-1.5 py-0.5 text-xs">{origin}/opds/</code>
            <code className="rounded bg-muted px-1.5 py-0.5 text-xs">{origin}/opds/v2/catalog</code>
          </dd>
        </div>
        <div className="rounded-lg border p-3">
          <dt className="flex items-center gap-1.5 font-medium"><MonitorSmartphone className="size-3.5" aria-hidden />{t("settings.keys.kosyncTitle")}</dt>
          <dd className="mt-1 text-muted-foreground">{t("settings.keys.kosyncHelp", { name: account.username })}</dd>
          <dd className="mt-2"><code className="rounded bg-muted px-1.5 py-0.5 text-xs">{origin}/kosync</code></dd>
        </div>
        <div className="rounded-lg border p-3 sm:col-span-2">
          <dt className="flex items-center gap-1.5 font-medium"><Tablet className="size-3.5" aria-hidden />{t("settings.keys.koboTitle")}</dt>
          <dd className="mt-1 text-muted-foreground">{t("settings.keys.koboHelp")}</dd>
          <dd className="mt-2"><code className="rounded bg-muted px-1.5 py-0.5 text-xs">api_endpoint={origin}/kobo/{t("settings.keys.koboKey")}</code></dd>
        </div>
      </dl>

      {shown && (
        <div role="status" className="mb-5 rounded-lg border border-primary/40 bg-primary/5 p-3">
          <p className="mb-2 text-sm font-medium">{t("settings.keys.once", { name: shown.name })}</p>
          <div className="flex gap-2">
            <Input readOnly value={shown.key} className="font-mono text-xs" aria-label={t("settings.keys.key")} onFocus={(e) => e.currentTarget.select()} />
            <Button variant="outline" onClick={() => void copy(shown.key)}>
              {copied ? <Check aria-hidden /> : <Copy aria-hidden />}
              {copied ? t("common.copied") : t("common.copy")}
            </Button>
          </div>
          {shown.purpose === "kobo" && (
            <div className="mt-3 space-y-1.5">
              <p className="text-sm">{t("settings.keys.koboLine")}</p>
              <Input readOnly value={`api_endpoint=${koboEndpoint(shown.key)}`} className="font-mono text-xs" aria-label={t("settings.keys.koboTitle")} onFocus={(e) => e.currentTarget.select()} />
            </div>
          )}
        </div>
      )}

      <form onSubmit={submit} className="mb-5 flex flex-wrap items-end gap-2">
        <div className="space-y-1.5">
          <Label>{t("settings.keys.purpose")}</Label>
          <Select value={purpose} onValueChange={(v) => setPurpose(v as (typeof PURPOSES)[number])}>
            <SelectTrigger className="w-44" aria-label={t("settings.keys.purpose")}>
              <SelectValue>{(v: string) => t(`settings.keys.purposes.${v as "opds"}`)}</SelectValue>
            </SelectTrigger>
            <SelectContent>
              {PURPOSES.map((p) => <SelectItem key={p} value={p}>{t(`settings.keys.purposes.${p}`)}</SelectItem>)}
            </SelectContent>
          </Select>
        </div>
        <div className="min-w-48 flex-1 space-y-1.5">
          <Label htmlFor="key-name">{t("settings.keys.name")}</Label>
          <Input id="key-name" name="name" placeholder={t("settings.keys.namePlaceholder")} maxLength={100} />
        </div>
        <Button type="submit" disabled={create.isPending}>{t("settings.keys.create")}</Button>
      </form>

      {keys.data && keys.data.length > 0 && (
        <ul className="divide-y rounded-lg border">
          {keys.data.map((key) => (
            <li key={key.id} className="flex items-center gap-3 px-3 py-2 text-sm">
              <div className="min-w-0 flex-1">
                <div className="truncate font-medium">{key.name}</div>
                <div className="text-xs text-muted-foreground">
                  {t(`settings.keys.purposes.${key.purpose as "opds"}`)} · <code>{key.prefix}…</code> ·{" "}
                  {key.last_used_at ? t("settings.keys.used", { when: format.relative(key.last_used_at) }) : t("settings.keys.unused")}
                </div>
              </div>
              <ConfirmDialog
                trigger={<Button variant="ghost" size="icon-sm" aria-label={t("settings.keys.revoke", { name: key.name })}><Trash2 aria-hidden /></Button>}
                title={t("settings.keys.revoke", { name: key.name })}
                description={t("settings.keys.revokeText")}
                confirm={t("settings.keys.revokeShort")}
                onConfirm={() => remove.mutateAsync({ params: { path: { key_id: key.id } } })}
              />
            </li>
          ))}
        </ul>
      )}

      <KoboDevices />

      {hasLegacyToken && (
        <div className="mt-5 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-dashed p-3 text-sm">
          <span className="text-muted-foreground">{t("settings.keys.legacy")}</span>
          <ConfirmDialog
            trigger={<Button variant="outline" size="sm">{t("settings.keys.revokeShort")}</Button>}
            title={t("settings.keys.legacyTitle")}
            description={t("settings.keys.legacyText")}
            confirm={t("settings.keys.revokeShort")}
            onConfirm={() => revokeLegacy.mutateAsync({})}
          />
        </div>
      )}
    </Section>
  );
}
