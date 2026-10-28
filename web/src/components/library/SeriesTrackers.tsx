import { useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { ListChecks, RefreshCw, Search, Unlink } from "lucide-react";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { api, errorMessage, fetchClient, type Schemas } from "@/api/client";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { format } from "@/i18n";

type Unit = Schemas["TrackerLinkIn"]["unit"];

/** "Spåra": the series at the user's connected trackers. Shown only when one is connected. */
export function SeriesTrackers({ seriesId, title }: { seriesId: number; title: string }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const trackers = api.useQuery("get", "/api/series/{series_id}/trackers", { params: { path: { series_id: seriesId } } });
  if (!trackers.data?.trackers.length) return null;
  const linked = trackers.data.trackers.filter((tracker) => tracker.link).length;
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger render={<Button variant="ghost" />}>
        <ListChecks aria-hidden />
        {t("trackers.track")}
        {linked > 0 && <Badge variant="secondary">{linked}</Badge>}
      </DialogTrigger>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{t("trackers.trackTitle", { title })}</DialogTitle>
          <DialogDescription>
            {t(trackers.data.default_unit === "volume" ? "trackers.readVolumes" : "trackers.readChapters", { count: trackers.data.progress })}
          </DialogDescription>
        </DialogHeader>
        <ul className="space-y-4">
          {trackers.data.trackers.map((tracker) => (
            <SeriesTracker key={tracker.service} seriesId={seriesId} title={title} tracker={tracker} defaultUnit={trackers.data.default_unit} />
          ))}
        </ul>
        <p className="text-xs text-muted-foreground">
          {t("trackers.howItWorks")} <Link to="/settings" hash="trackers" className="underline">{t("trackers.manage")}</Link>
        </p>
      </DialogContent>
    </Dialog>
  );
}

function SeriesTracker({ seriesId, title, tracker, defaultUnit }: {
  seriesId: number; title: string; tracker: Schemas["SeriesTrackerOut"]; defaultUnit: Unit;
}) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [query, setQuery] = useState(title);
  const [searching, setSearching] = useState(false);
  const [unit, setUnit] = useState<Unit>(tracker.units.includes(defaultUnit) ? defaultUnit : tracker.units[0]!);
  const results = api.useQuery(
    "get",
    "/api/trackers/{name}/search",
    { params: { path: { name: tracker.service }, query: { q: query } } },
    { enabled: searching && query.trim().length >= 2 },
  );
  const refresh = () => queryClient.invalidateQueries({ queryKey: ["get", "/api/series/{series_id}/trackers"] });
  const path = { series_id: seriesId, name: tracker.service };
  const link = async (remoteId: string, remoteTitle: string) => {
    const { data, error } = await fetchClient.PUT("/api/series/{series_id}/trackers/{name}", {
      params: { path }, body: { remote_id: remoteId, title: remoteTitle, unit },
    });
    if (error || !data) return void toast.error(errorMessage(error, t("common.errorGeneric")));
    if (data.error) toast.error(data.error);
    else toast.success(t("trackers.linked", { name: tracker.title }));
    setSearching(false);
    await refresh();
  };
  const unlink = async () => {
    const { error } = await fetchClient.DELETE("/api/series/{series_id}/trackers/{name}", { params: { path } });
    if (error) return void toast.error(errorMessage(error, t("common.errorGeneric")));
    await refresh();
  };
  const sync = async () => {
    const { data, error } = await fetchClient.POST("/api/series/{series_id}/trackers/sync", { params: { path: { series_id: seriesId } } });
    if (error) return void toast.error(errorMessage(error, t("common.errorGeneric")));
    const failed = data?.find((row) => row.error);
    if (failed?.error) toast.error(failed.error);
    else toast.success(t("trackers.synced"));
    await refresh();
  };
  const search = (event: FormEvent) => {
    event.preventDefault();
    setSearching(true);
    void results.refetch();
  };
  const current = tracker.link;
  return (
    <li className="space-y-2 rounded-lg border p-3 text-sm" aria-label={tracker.title}>
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-medium">{tracker.title}</span>
        {current && <span className="min-w-0 flex-1 truncate text-muted-foreground">{current.title}</span>}
      </div>
      {current ? (
        <>
          <p className="text-xs text-muted-foreground">
            {current.sent_at
              ? t(current.unit === "volume" ? "trackers.sentVolumes" : "trackers.sentChapters", { count: current.sent_progress, when: format.relative(current.sent_at) })
              : t("trackers.notSent")}
          </p>
          {current.error && <p className="text-xs text-destructive">{current.error}</p>}
          <div className="flex gap-2">
            <Button size="sm" variant="outline" onClick={() => void sync()}><RefreshCw aria-hidden />{t("trackers.syncNow")}</Button>
            <Button size="sm" variant="ghost" onClick={() => void unlink()}><Unlink aria-hidden />{t("trackers.unlink")}</Button>
          </div>
        </>
      ) : (
        <>
          {tracker.units.length > 1 && (
            <ToggleGroup value={[unit]} onValueChange={(v: string[]) => v[0] && setUnit(v[0] as Unit)} variant="outline" size="sm" aria-label={t("trackers.unit")}>
              <ToggleGroupItem value="volume">{t("trackers.volumes")}</ToggleGroupItem>
              <ToggleGroupItem value="chapter">{t("trackers.chapters")}</ToggleGroupItem>
            </ToggleGroup>
          )}
          {tracker.suggested_id && (
            <Button size="sm" onClick={() => void link(tracker.suggested_id!, title)}>{t("trackers.linkSuggested", { name: tracker.title, id: tracker.suggested_id })}</Button>
          )}
          <form onSubmit={search} className="flex gap-2">
            <Input value={query} onChange={(e) => setQuery(e.target.value)} aria-label={t("trackers.searchAt", { name: tracker.title })} />
            <Button type="submit" size="sm" variant="outline"><Search aria-hidden />{t("common.search")}</Button>
          </form>
          {searching && results.data && (
            results.data.length === 0 ? (
              <p className="text-xs text-muted-foreground">{t("trackers.noHits")}</p>
            ) : (
              <ul className="max-h-60 divide-y overflow-y-auto rounded-md border">
                {results.data.map((hit) => (
                  <li key={hit.id}>
                    <button type="button" className="flex w-full items-center gap-3 px-2 py-1.5 text-left hover:bg-accent" onClick={() => void link(hit.id, hit.title)}>
                      {hit.cover ? <img src={hit.cover} alt="" className="h-12 w-8 shrink-0 rounded object-cover" loading="lazy" referrerPolicy="no-referrer" /> : <span className="h-12 w-8 shrink-0 rounded bg-muted" />}
                      <span className="min-w-0 flex-1">
                        <span className="block truncate">{hit.title}</span>
                        <span className="text-xs text-muted-foreground">
                          {[hit.year, hit.volumes && t("trackers.volumeCount", { count: hit.volumes }), hit.chapters && t("trackers.chapterCount", { count: hit.chapters })].filter(Boolean).join(" · ")}
                        </span>
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            )
          )}
          {searching && results.isError && <p className="text-xs text-destructive">{errorMessage(results.error, t("common.errorGeneric"))}</p>}
        </>
      )}
    </li>
  );
}
