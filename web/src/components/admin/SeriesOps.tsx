import { useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { Merge } from "lucide-react";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { api, errorMessage, fetchClient } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

function useRefreshSeries() {
  const queryClient = useQueryClient();
  return async () => {
    await queryClient.invalidateQueries({ queryKey: ["get", "/api/books"] });
    await queryClient.invalidateQueries({ queryKey: ["get", "/api/series"] });
    await queryClient.invalidateQueries({ queryKey: ["get", "/api/series/{series_id}"] });
  };
}

/** Selected books become a series of their own. */
export function SplitButton({ seriesId, bookIds, done }: { seriesId: number; bookIds: number[]; done: () => void }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const refresh = useRefreshSeries();
  const [open, setOpen] = useState(false);
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const title = String(new FormData(event.currentTarget).get("title") ?? "").trim();
    const { data, error } = await fetchClient.POST("/api/matching/series/{series_id}/split", { params: { path: { series_id: seriesId } }, body: { book_ids: bookIds, title } });
    if (error || !data) return void toast.error(errorMessage(error, t("common.errorGeneric")));
    setOpen(false);
    done();
    await refresh();
    await navigate({ to: "/series/$seriesId", params: { seriesId: data.series_id } });
  };
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger render={<Button size="sm" variant="outline" disabled={bookIds.length === 0} />}>{t("seriesOps.split")}</DialogTrigger>
      <DialogContent className="sm:max-w-md">
        <DialogHeader><DialogTitle>{t("seriesOps.splitTitle", { count: bookIds.length })}</DialogTitle></DialogHeader>
        <form onSubmit={(e) => void submit(e)} className="grid gap-4">
          <div className="space-y-1.5">
            <Label htmlFor="split-title">{t("seriesOps.newTitle")}</Label>
            <Input id="split-title" name="title" required autoFocus />
          </div>
          <DialogFooter>
            <Button type="button" variant="ghost" onClick={() => setOpen(false)}>{t("common.cancel")}</Button>
            <Button type="submit">{t("seriesOps.split")}</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

/** Selected books move to another series in the same library. */
export function MoveButton({ libraryId, seriesId, bookIds, done }: { libraryId: number; seriesId: number; bookIds: number[]; done: () => void }) {
  const { t } = useTranslation();
  const refresh = useRefreshSeries();
  const [open, setOpen] = useState(false);
  const [target, setTarget] = useState("");
  const series = api.useQuery("get", "/api/series", { params: { query: { library_id: libraryId, limit: 2000 } } }, { enabled: open });
  const move = async () => {
    const { error } = await fetchClient.POST("/api/matching/books/move", { body: { book_ids: bookIds, target_series_id: Number(target) } });
    if (error) return void toast.error(errorMessage(error, t("common.errorGeneric")));
    toast.success(t("seriesOps.moved", { count: bookIds.length }));
    setOpen(false);
    done();
    await refresh();
  };
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger render={<Button size="sm" variant="outline" disabled={bookIds.length === 0} />}>{t("seriesOps.move")}</DialogTrigger>
      <DialogContent className="sm:max-w-md">
        <DialogHeader><DialogTitle>{t("seriesOps.moveTitle", { count: bookIds.length })}</DialogTitle></DialogHeader>
        <Select value={target} onValueChange={(v) => setTarget(String(v))}>
          <SelectTrigger className="w-full" aria-label={t("seriesOps.target")}>
            <SelectValue placeholder={t("seriesOps.target")}>{(v: string) => series.data?.find((s) => String(s.id) === v)?.title ?? t("seriesOps.target")}</SelectValue>
          </SelectTrigger>
          <SelectContent>
            {(series.data ?? []).filter((s) => s.id !== seriesId).map((s) => <SelectItem key={s.id} value={String(s.id)}>{s.title}{s.start_year ? ` (${s.start_year})` : ""}</SelectItem>)}
          </SelectContent>
        </Select>
        <DialogFooter>
          <Button variant="ghost" onClick={() => setOpen(false)}>{t("common.cancel")}</Button>
          <Button onClick={() => void move()} disabled={!target}>{t("seriesOps.move")}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/** Other series in the library are merged into this one. */
export function MergeDialog({ libraryId, seriesId }: { libraryId: number; seriesId: number }) {
  const { t } = useTranslation();
  const refresh = useRefreshSeries();
  const [open, setOpen] = useState(false);
  const [filter, setFilter] = useState("");
  const [chosen, setChosen] = useState<Set<number>>(new Set());
  const series = api.useQuery("get", "/api/series", { params: { query: { library_id: libraryId, limit: 2000 } } }, { enabled: open });
  const merge = async () => {
    const { error } = await fetchClient.POST("/api/matching/series/{series_id}/merge", { params: { path: { series_id: seriesId } }, body: { source_series_ids: [...chosen] } });
    if (error) return void toast.error(errorMessage(error, t("common.errorGeneric")));
    toast.success(t("seriesOps.merged", { count: chosen.size }));
    setOpen(false);
    setChosen(new Set());
    await refresh();
  };
  const shown = (series.data ?? []).filter((s) => s.id !== seriesId && s.title.toLowerCase().includes(filter.toLowerCase()));
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger render={<Button variant="ghost" />}><Merge aria-hidden />{t("seriesOps.merge")}</DialogTrigger>
      <DialogContent className="sm:max-w-md">
        <DialogHeader><DialogTitle>{t("seriesOps.mergeTitle")}</DialogTitle></DialogHeader>
        <Input value={filter} onChange={(e) => setFilter(e.target.value)} placeholder={t("common.search")} aria-label={t("common.search")} autoFocus />
        <ul className="max-h-[45dvh] divide-y overflow-y-auto rounded-lg border">
          {shown.map((s) => (
            <li key={s.id}>
              <label className="flex items-center gap-3 px-3 py-2 text-sm">
                <Checkbox checked={chosen.has(s.id)} onCheckedChange={(on) => setChosen((current) => { const next = new Set(current); if (on) next.add(s.id); else next.delete(s.id); return next; })} />
                <span className="min-w-0 flex-1 truncate">{s.title}{s.start_year ? ` (${s.start_year})` : ""}</span>
                <span className="text-xs text-muted-foreground">{t("review.bookCount", { count: s.book_count })}</span>
              </label>
            </li>
          ))}
        </ul>
        <DialogFooter>
          <Button variant="ghost" onClick={() => setOpen(false)}>{t("common.cancel")}</Button>
          <Button onClick={() => void merge()} disabled={chosen.size === 0}>{t("seriesOps.mergeInto", { count: chosen.size })}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
