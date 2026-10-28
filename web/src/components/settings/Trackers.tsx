import { useQueryClient } from "@tanstack/react-query";
import { ListChecks } from "lucide-react";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { api, errorMessage, fetchClient, type Schemas } from "@/api/client";
import { Section } from "@/components/settings/Section";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { format } from "@/i18n";

const TRACKERS = ["get", "/api/trackers"] as const;

/** Trackers: the user's accounts at MangaUpdates, Kitsu, AniList and MyAnimeList (kodex.reading.trackers). */
export function TrackersSection() {
  const { t } = useTranslation();
  const trackers = api.useQuery("get", "/api/trackers");
  if (!trackers.data) return null;
  return (
    <Section icon={ListChecks} title={t("trackers.title")} description={t("trackers.intro")}>
      <div id="trackers" className="scroll-mt-20" />
      {!trackers.data.available && <p className="mb-3 rounded-lg border border-dashed p-3 text-sm text-muted-foreground">{t("trackers.noSecret")}</p>}
      <ul className="divide-y rounded-lg border" aria-label={t("trackers.title")}>
        {trackers.data.services.map((tracker) => (
          <Tracker key={tracker.name} tracker={tracker} available={trackers.data.available} />
        ))}
      </ul>
    </Section>
  );
}

function Tracker({ tracker, available }: { tracker: Schemas["TrackerServiceOut"]; available: boolean }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const refresh = () => queryClient.invalidateQueries({ queryKey: TRACKERS });
  const disconnect = async () => {
    const { error } = await fetchClient.DELETE("/api/trackers/{name}", { params: { path: { name: tracker.name } } });
    if (error) return void toast.error(errorMessage(error, t("common.errorGeneric")));
    toast.success(t("trackers.disconnected", { name: tracker.title }));
    await refresh();
  };
  const authorize = async () => {
    const { data, error } = await fetchClient.POST("/api/trackers/{name}/authorize", { params: { path: { name: tracker.name } } });
    if (error || !data) return void toast.error(errorMessage(error, t("common.errorGeneric")));
    window.location.assign(data.url);
  };
  return (
    <li className="space-y-3 px-3 py-3 text-sm">
      <div className="flex flex-wrap items-center gap-3">
        <div className="min-w-0 flex-1">
          <div className="font-medium">{tracker.title}</div>
          <div className="text-xs text-muted-foreground">
            {tracker.account
              ? t("trackers.connectedAs", { name: tracker.account.username, when: format.relative(tracker.account.connected_at) })
              : !tracker.configured
                ? t("trackers.needsClient", { name: tracker.title })
                : tracker.units.length === 1
                  ? t("trackers.chaptersOnly")
                  : t("trackers.notConnected")}
          </div>
        </div>
        {tracker.account ? (
          <Button variant="outline" size="sm" onClick={() => void disconnect()}>{t("trackers.disconnect")}</Button>
        ) : tracker.login === "oauth" ? (
          <Button size="sm" disabled={!available || !tracker.configured} onClick={() => void authorize()}>{t("trackers.connectAt", { name: tracker.title })}</Button>
        ) : (
          <Button size="sm" variant={open ? "ghost" : "default"} disabled={!available} onClick={() => setOpen(!open)}>
            {open ? t("common.cancel") : t("trackers.connect")}
          </Button>
        )}
      </div>
      {open && !tracker.account && <PasswordLogin tracker={tracker} done={() => { setOpen(false); void refresh(); }} />}
    </li>
  );
}

function PasswordLogin({ tracker, done }: { tracker: Schemas["TrackerServiceOut"]; done: () => void }) {
  const { t } = useTranslation();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    const { error } = await fetchClient.POST("/api/trackers/{name}/login", { params: { path: { name: tracker.name } }, body: { username, password } });
    setBusy(false);
    if (error) return void toast.error(errorMessage(error, t("common.errorGeneric")));
    toast.success(t("trackers.connected", { name: tracker.title }));
    done();
  };
  const id = `tracker-${tracker.name}`;
  return (
    <form onSubmit={(e) => void submit(e)} className="grid gap-3 sm:grid-cols-[1fr_1fr_auto] sm:items-end">
      <div className="space-y-1">
        <Label htmlFor={`${id}-user`}>{tracker.name === "kitsu" ? t("trackers.email") : t("trackers.username")}</Label>
        <Input id={`${id}-user`} value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" required />
      </div>
      <div className="space-y-1">
        <Label htmlFor={`${id}-password`}>{t("trackers.password")}</Label>
        <Input id={`${id}-password`} type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" required />
      </div>
      <Button type="submit" disabled={busy || !username || !password}>{t("trackers.connect")}</Button>
      <p className="text-xs text-muted-foreground sm:col-span-3">{t("trackers.passwordNote", { name: tracker.title })}</p>
    </form>
  );
}
