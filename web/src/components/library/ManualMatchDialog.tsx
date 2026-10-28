import { useQueryClient } from "@tanstack/react-query";
import { ChevronLeft, RefreshCw, Search } from "lucide-react";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { errorMessage, fetchClient, type Schemas } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";

type Candidate = Schemas["CandidateOut"];
type Diff = Record<string, Schemas["FieldDiffOut"]>;

function show(value: unknown): string {
  if (value == null || value === "") return "–";
  if (Array.isArray(value)) return value.join(", ");
  return String(value);
}

/** An admin matches one book by hand: search, pick a volume (and an issue), review the changes, apply. */
export function ManualMatchDialog({ book, initialQuery }: { book: Schemas["BookOut"]; initialQuery: string }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState(initialQuery);
  const [candidates, setCandidates] = useState<Candidate[] | null>(null);
  const [volume, setVolume] = useState<Candidate | null>(null);
  const [issues, setIssues] = useState<Candidate[] | null>(null);
  const [target, setTarget] = useState<{ candidate: Candidate; isIssue: boolean } | null>(null);
  const [diff, setDiff] = useState<Diff | null>(null);
  const [fields, setFields] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const path = { book_id: book.id };

  const search = async (event?: FormEvent) => {
    event?.preventDefault();
    setBusy(true);
    const { data, error } = await fetchClient.GET("/api/books/{book_id}/enrichment/search", { params: { path, query: { query } } });
    setBusy(false);
    if (error) toast.error(errorMessage(error, t("review.searchFailed")));
    setCandidates(data ?? []);
  };
  const pick = async (candidate: Candidate) => {
    if (candidate.provider === "comicvine") {
      setVolume(candidate);
      setBusy(true);
      const { data } = await fetchClient.GET("/api/books/{book_id}/enrichment/volumes/{volume_id}/issues", { params: { path: { ...path, volume_id: candidate.external_id }, query: { provider: candidate.provider } } });
      setBusy(false);
      setIssues(data ?? []);
      return;
    }
    await review(candidate, false);
  };
  const review = async (candidate: Candidate, isIssue: boolean) => {
    setTarget({ candidate, isIssue });
    setBusy(true);
    const { data } = await fetchClient.GET("/api/books/{book_id}/enrichment/preview", { params: { path, query: { provider: candidate.provider, external_id: candidate.external_id, is_issue: isIssue } } });
    setBusy(false);
    const changes = (data ?? {}) as Diff;
    setDiff(changes);
    setFields(new Set(Object.keys(changes)));
  };
  const apply = async () => {
    if (!target) return;
    setBusy(true);
    const { data, error } = await fetchClient.POST("/api/books/{book_id}/enrichment/apply", {
      params: { path },
      body: { provider: target.candidate.provider, external_id: target.candidate.external_id, is_issue: target.isIssue, fields: [...fields] } as never,
    });
    setBusy(false);
    if (error || !data?.changed) return void toast.error(errorMessage(error, t("match.failed")));
    toast.success(t("match.applied"));
    setOpen(false);
    await queryClient.invalidateQueries({ queryKey: ["get", "/api/books/{book_id}"] });
  };
  const reset = () => {
    setCandidates(null);
    setVolume(null);
    setIssues(null);
    setTarget(null);
    setDiff(null);
  };

  const list = (items: Candidate[], onPick: (c: Candidate) => void) => (
    <ul className="max-h-[50dvh] divide-y overflow-y-auto rounded-lg border">
      {items.map((c) => (
        <li key={`${c.provider}:${c.external_id}`}>
          <button type="button" onClick={() => onPick(c)} disabled={busy} className="flex w-full items-center gap-3 p-2 text-left hover:bg-muted">
            {c.thumbnail_url ? <img src={c.thumbnail_url} alt="" referrerPolicy="no-referrer" className="h-16 w-11 shrink-0 rounded object-cover" /> : <span className="h-16 w-11 shrink-0 rounded bg-muted" />}
            <span className="min-w-0">
              <span className="block truncate text-sm font-medium">{c.title}</span>
              <span className="block truncate text-xs text-muted-foreground">{[c.year, c.subtitle, c.provider].filter(Boolean).join(" · ")}</span>
            </span>
          </button>
        </li>
      ))}
      {items.length === 0 && <li className="p-3 text-sm text-muted-foreground">{t("review.noCandidates")}</li>}
    </ul>
  );

  return (
    <Dialog open={open} onOpenChange={(value) => { setOpen(value); if (value && !candidates) void search(); if (!value) reset(); }}>
      <DialogTrigger render={<Button variant="outline" size="sm" />}>
        <RefreshCw aria-hidden />
        {t("match.button")}
      </DialogTrigger>
      <DialogContent className="sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>{diff ? t("match.review") : volume ? t("match.pickIssue") : t("match.title")}</DialogTitle>
        </DialogHeader>
        {diff && target ? (
          <div className="space-y-3">
            {Object.keys(diff).length === 0 ? (
              <p className="text-sm text-muted-foreground">{t("match.noChanges")}</p>
            ) : (
              <ul className="max-h-[50dvh] space-y-2 overflow-y-auto">
                {Object.entries(diff).map(([field, change]) => (
                  <li key={field} className="flex gap-3 rounded-lg border p-2 text-sm">
                    <Checkbox checked={fields.has(field)} onCheckedChange={(on) => setFields((current) => { const next = new Set(current); if (on) next.add(field); else next.delete(field); return next; })} aria-label={field} />
                    <span className="min-w-0 flex-1">
                      <span className="block font-medium">{t(`book.${field}`, { defaultValue: field })}</span>
                      <span className="block text-xs text-muted-foreground line-through">{show(change.current)}</span>
                      <span className="block text-xs">{show(change.incoming)}</span>
                    </span>
                  </li>
                ))}
              </ul>
            )}
            <DialogFooter>
              <Button variant="ghost" onClick={() => { setDiff(null); setTarget(null); }}><ChevronLeft aria-hidden />{t("common.back")}</Button>
              <Button onClick={() => void apply()} disabled={busy || fields.size === 0}>{t("match.apply")}</Button>
            </DialogFooter>
          </div>
        ) : volume ? (
          <div className="space-y-3">
            <p className="text-sm">{volume.title}</p>
            {issues === null ? <p className="text-sm text-muted-foreground">{t("common.loading")}</p> : list(issues, (issue) => void review(issue, true))}
            <DialogFooter>
              <Button variant="ghost" onClick={() => { setVolume(null); setIssues(null); }}><ChevronLeft aria-hidden />{t("common.back")}</Button>
              <Button variant="outline" onClick={() => void review(volume, false)} disabled={busy}>{t("match.wholeVolume")}</Button>
            </DialogFooter>
          </div>
        ) : (
          <div className="space-y-3">
            <form onSubmit={(e) => void search(e)} className="flex gap-2">
              <Input value={query} onChange={(e) => setQuery(e.target.value)} aria-label={t("common.search")} autoFocus />
              <Button type="submit" variant="outline" disabled={busy}><Search aria-hidden />{t("common.search")}</Button>
            </form>
            {candidates === null ? <p className="text-sm text-muted-foreground">{t("common.loading")}</p> : list(candidates, (c) => void pick(c))}
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
