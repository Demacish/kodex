import { useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { Check, ClipboardCopy, ExternalLink, Search, SkipForward, Undo2, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { api, errorMessage, fetchClient, type Schemas } from "@/api/client";
import { EmptyState, ErrorState, PageHeader } from "@/components/common/states";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { format } from "@/i18n";
import { cn } from "@/lib/utils";

type Review = Schemas["ReviewOut"];
type Candidate = Schemas["MatchCandidateOut"];
export type ReviewTab = "open" | "auto" | "resolved" | "dismissed";
const TABS: ReviewTab[] = ["open", "auto", "resolved", "dismissed"];
const PROVIDERS: Record<string, string> = {
  comicvine: "Comic Vine", metron: "Metron", mangadex: "MangaDex", anilist: "AniList", mangaupdates: "MangaUpdates",
  open_library: "Open Library", google_books: "Google Books", hardcover: "Hardcover",
};
const GOLDEN_FIELDS = ["series", "title", "volume", "volume_end", "issue", "issue_count", "chapter", "chapter_end", "year", "series_year", "format", "ambiguous"];

interface Parsed {
  titles?: string[];
  start_year?: number | null;
  years?: number[];
  publisher?: string | null;
  numbers?: (number | string)[];
  format_family?: string;
  kind?: string;
  reason?: string;
  moves?: Record<string, { key: string; title: string; book_ids: number[]; target_series_id: number | null }>;
  parsed_names?: { name: string; parsed: Record<string, unknown> }[];
}

function parsedOf(review: Review): Parsed {
  return (review.parsed ?? {}) as Parsed;
}

/**
 * The matching review queue (backend: kodex/matching): uncertain matches,
 * regroup proposals and the log of automatic decisions, biggest first.
 * Keys: j/k move, 1–3 choose, n no match, d skip, s search, u undo,
 * a/r accept or reject a regroup.
 */
export function ReviewQueue({ tab, onTab }: { tab: ReviewTab; onTab: (tab: ReviewTab) => void }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  // Refreshes while matching jobs may be adding to it.
  const reviews = api.useQuery("get", "/api/matching/reviews", { params: { query: { status: tab, limit: 200 } } }, { refetchInterval: 20_000 });
  const [index, setIndex] = useState(0);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [lastDecided, setLastDecided] = useState<number[]>([]);
  const [busy, setBusy] = useState(false);
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<Candidate[] | null>(null);
  const items = useMemo(() => reviews.data?.items ?? [], [reviews.data]);
  const current: Review | undefined = items[Math.min(index, Math.max(0, items.length - 1))];

  useEffect(() => {
    setResults(null);
    setQuery(parsedOf(current ?? ({} as Review)).titles?.[0] ?? current?.title ?? "");
  }, [current?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    setIndex(0);
    setSelected(new Set());
  }, [tab]);

  const refresh = useCallback(async () => {
    await queryClient.invalidateQueries({ queryKey: ["get", "/api/matching/reviews"] });
  }, [queryClient]);

  const act = useCallback(
    async (call: () => Promise<{ error?: unknown }>, id: number) => {
      if (busy) return;
      setBusy(true);
      try {
        const { error } = await call();
        if (error) return void toast.error(errorMessage(error, t("common.errorGeneric")));
        setLastDecided([id]);
        await refresh();
      } finally {
        setBusy(false);
      }
    },
    [busy, refresh, t],
  );

  const path = (review: Review) => ({ params: { path: { review_id: review.id } } });
  const choose = useCallback(
    (candidate: Candidate | undefined) => {
      if (!current || !candidate) return;
      void act(() => fetchClient.POST("/api/matching/reviews/{review_id}/choose", { ...path(current), body: { provider: candidate.provider, id: candidate.id } }), current.id);
    },
    [act, current],
  );
  const noMatch = useCallback(() => current && void act(() => fetchClient.POST("/api/matching/reviews/{review_id}/no-match", path(current)), current.id), [act, current]);
  const dismiss = useCallback(() => current && void act(() => fetchClient.POST("/api/matching/reviews/{review_id}/dismiss", path(current)), current.id), [act, current]);
  const revert = useCallback(() => current && void act(() => fetchClient.POST("/api/matching/reviews/{review_id}/revert", path(current)), current.id), [act, current]);
  const regroup = useCallback(
    (accept: boolean) => current && void act(() => fetchClient.POST("/api/matching/reviews/{review_id}/regroup", { params: { path: { review_id: current.id }, query: { accept } } }), current.id),
    [act, current],
  );

  const undo = useCallback(async () => {
    if (lastDecided.length === 0) return;
    setBusy(true);
    try {
      for (const id of lastDecided) await fetchClient.POST("/api/matching/reviews/{review_id}/revert", { params: { path: { review_id: id } } });
      setLastDecided([]);
      toast.success(t("review.undone"));
      await refresh();
    } finally {
      setBusy(false);
    }
  }, [lastDecided, refresh, t]);

  const bulk = async (action: "accept_best" | "no_match" | "dismiss") => {
    setBusy(true);
    try {
      const { data } = await fetchClient.POST("/api/matching/reviews/bulk", { body: { review_ids: [...selected], action } });
      setLastDecided(data?.done ?? []);
      if (data?.failed.length) toast.error(t("review.bulkFailed", { count: data.failed.length }));
      else toast.success(t("review.bulkDone", { count: data?.done.length ?? 0 }));
      setSelected(new Set());
      await refresh();
    } finally {
      setBusy(false);
    }
  };

  const search = async (event?: FormEvent) => {
    event?.preventDefault();
    if (!current || !query.trim()) return;
    setBusy(true);
    try {
      const { data, error } = await fetchClient.POST("/api/matching/reviews/{review_id}/search", { ...path(current), body: { query: query.trim() } });
      if (error) toast.error(errorMessage(error, t("review.searchFailed")));
      setResults(data ?? []);
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (target?.closest("input, textarea, [role=dialog]") || event.metaKey || event.ctrlKey || event.altKey) return;
      const candidates = results ?? current?.candidates ?? [];
      if (event.key === "j") setIndex((i) => Math.min(i + 1, items.length - 1));
      else if (event.key === "k") setIndex((i) => Math.max(i - 1, 0));
      else if (event.key === "u") void undo();
      else if (!current || tab !== "open") return;
      else if (["1", "2", "3"].includes(event.key) && current.kind !== "regroup") choose(candidates[Number(event.key) - 1]);
      else if (event.key === "n" && current.kind === "series_match") noMatch();
      else if (event.key === "d") dismiss();
      else if (event.key === "a" && current.kind === "regroup") regroup(true);
      else if (event.key === "r" && current.kind === "regroup") regroup(false);
      else if (event.key === "s") document.getElementById("review-search")?.focus();
      else return;
      event.preventDefault();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [choose, current, dismiss, items.length, noMatch, regroup, results, tab, undo]);

  const counts = reviews.data?.counts ?? {};
  const candidates = results ?? current?.candidates ?? [];

  return (
    <div>
      <PageHeader
        title={t("review.title")}
        description={t("review.intro")}
        actions={
          <>
            {lastDecided.length > 0 && (
              <Button variant="outline" size="sm" onClick={() => void undo()} disabled={busy}>
                <Undo2 aria-hidden />
                {t("review.undo", { count: lastDecided.length })}
              </Button>
            )}
            {tab === "open" && selected.size > 0 && (
              <>
                <Button size="sm" onClick={() => void bulk("accept_best")} disabled={busy}>{t("review.acceptBest", { count: selected.size })}</Button>
                <Button size="sm" variant="outline" onClick={() => void bulk("no_match")} disabled={busy}>{t("review.noMatchMany", { count: selected.size })}</Button>
              </>
            )}
          </>
        }
      />
      <Tabs value={tab} onValueChange={(value) => onTab(value as ReviewTab)} className="mb-4">
        <TabsList>
          {TABS.map((key) => (
            <TabsTrigger key={key} value={key}>
              {t(`review.tabs.${key}`)}
              {counts[key] ? <span className="ml-1 text-xs opacity-70 tabular-nums">{counts[key]}</span> : null}
            </TabsTrigger>
          ))}
        </TabsList>
      </Tabs>

      {reviews.isError ? (
        <ErrorState error={reviews.error} onRetry={() => void reviews.refetch()} />
      ) : reviews.isPending ? (
        <div className="grid gap-4 lg:grid-cols-[22rem_1fr]">
          <Skeleton className="h-96 rounded-xl" />
          <Skeleton className="h-96 rounded-xl" />
        </div>
      ) : items.length === 0 ? (
        <EmptyState icon={Check} title={tab === "open" ? t("review.allDone") : t("states.emptyTitle")}>{tab === "open" ? t("review.allDoneText") : null}</EmptyState>
      ) : (
        <div className="grid gap-4 lg:grid-cols-[minmax(16rem,22rem)_1fr]">
          <ul className="max-h-[70dvh] space-y-0.5 overflow-y-auto rounded-xl border bg-card p-1.5" aria-label={t("review.queue")}>
            {items.map((item, i) => (
              <li key={item.id}>
                <div className={cn("flex items-center gap-2 rounded-lg px-2 py-1.5 text-sm", item.id === current?.id ? "bg-accent text-accent-foreground" : "hover:bg-muted")}>
                  {tab === "open" && (
                    <Checkbox
                      checked={selected.has(item.id)}
                      onCheckedChange={(checked) => {
                        const next = new Set(selected);
                        if (checked) next.add(item.id);
                        else next.delete(item.id);
                        setSelected(next);
                      }}
                      aria-label={t("review.select", { title: item.title })}
                    />
                  )}
                  <button type="button" className="flex min-w-0 flex-1 items-center justify-between gap-2 text-left" onClick={() => setIndex(i)} aria-current={item.id === current?.id ? "true" : undefined}>
                    <span className="truncate">
                      {item.title}
                      {listHint(item, t) && <span className="ml-1 text-xs text-muted-foreground">{listHint(item, t)}</span>}
                    </span>
                    <span className="shrink-0 text-xs text-muted-foreground tabular-nums">
                      {item.kind === "regroup" ? t("review.regroupShort") : item.best_score != null ? Math.round(item.best_score * 100) : "–"} · {t("review.bookCount", { count: item.book_count })}
                    </span>
                  </button>
                </div>
              </li>
            ))}
          </ul>

          {current && (
            <section className="min-w-0 space-y-4" aria-live="polite" aria-label={current.title}>
              <ReviewHeader review={current} />
              {current.kind === "regroup" ? (
                <Regroup review={current} open={tab === "open"} onAccept={() => regroup(true)} onReject={() => regroup(false)} />
              ) : (
                <>
                  <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                    {candidates.slice(0, 6).map((candidate, i) => (
                      <CandidateCard key={`${candidate.provider}:${candidate.id}`} candidate={candidate} shortcut={i < 3 ? String(i + 1) : undefined}
                        onChoose={tab === "open" ? () => choose(candidate) : undefined} busy={busy} />
                    ))}
                    {candidates.length === 0 && <p className="text-sm text-muted-foreground">{t("review.noCandidates")}</p>}
                  </div>
                  {tab === "open" && (
                    <div className="flex flex-wrap items-center gap-2">
                      <form onSubmit={(e) => void search(e)} className="flex items-center gap-2">
                        <Input id="review-search" value={query} onChange={(e) => setQuery(e.target.value)} className="w-64" placeholder={t("review.searchOther")} aria-label={t("review.searchOther")} />
                        <Button type="submit" variant="outline" disabled={busy}><Search aria-hidden />{t("common.search")}</Button>
                      </form>
                      {current.kind === "series_match" && (
                        <Button variant="outline" onClick={noMatch} disabled={busy}><X aria-hidden />{t("review.noMatch")}</Button>
                      )}
                      <Button variant="ghost" onClick={dismiss} disabled={busy}><SkipForward aria-hidden />{t("review.skip")}</Button>
                    </div>
                  )}
                  {(tab === "auto" || tab === "resolved") && (
                    <Button variant="outline" onClick={revert} disabled={busy}><Undo2 aria-hidden />{tab === "auto" ? t("review.revert") : t("review.reopen")}</Button>
                  )}
                </>
              )}
              <ParsedNames review={current} />
            </section>
          )}
        </div>
      )}
      <p className="mt-6 text-xs text-muted-foreground">{t("review.keys")}</p>
    </div>
  );
}

function listHint(review: Review, t: (key: "review.families.collected") => string): string {
  const parsed = parsedOf(review);
  const family = parsed.format_family && parsed.format_family !== "issue" ? t(`review.families.${parsed.format_family as "collected"}`) : null;
  return [parsed.start_year, family].filter(Boolean).join(" · ");
}

function ReviewHeader({ review }: { review: Review }) {
  const { t } = useTranslation();
  const p = parsedOf(review);
  const facts = [
    p.start_year && t("review.startYear", { year: p.start_year }),
    p.years?.length ? t("review.years", { range: p.years.length > 1 ? `${p.years[0]}–${p.years[p.years.length - 1]}` : String(p.years[0]) }) : null,
    p.publisher,
    p.numbers?.length ? t("review.numbers", { list: p.numbers.slice(0, 8).join(", ") + (p.numbers.length > 8 ? " …" : "") }) : null,
  ].filter(Boolean);
  return (
    <div>
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="text-xl font-semibold">{review.title}</h2>
        <Badge variant="outline">{t(`review.kinds.${review.kind as "series_match"}`)}</Badge>
        {review.series_id != null && (
          <Link to="/series/$seriesId" params={{ seriesId: review.series_id }} className="inline-flex items-center gap-1 text-xs text-primary-text hover:underline">
            {t("review.openSeries")}
            <ExternalLink className="size-3" aria-hidden />
          </Link>
        )}
      </div>
      <p className="text-sm text-muted-foreground">{[t("review.bookCount", { count: review.book_count }), ...facts].join(" · ")}</p>
      {p.reason && <p className="mt-1 text-xs text-muted-foreground">{t("review.why", { reason: p.reason })}</p>}
      {review.decided_at && <p className="mt-1 text-xs text-muted-foreground">{t("review.decided", { when: format.relative(review.decided_at) })}</p>}
    </div>
  );
}

function CandidateCard({ candidate, shortcut, onChoose, busy }: { candidate: Candidate; shortcut?: string; onChoose?: () => void; busy: boolean }) {
  const { t } = useTranslation();
  return (
    <article className={cn("flex flex-col gap-3 rounded-xl border bg-card p-3", candidate.disqualified && "opacity-60")}>
      <div className="flex gap-3">
        {candidate.cover_url ? (
          <img src={candidate.cover_url} alt="" loading="lazy" referrerPolicy="no-referrer" className="h-28 w-20 shrink-0 rounded object-cover" />
        ) : (
          <div className="h-28 w-20 shrink-0 rounded bg-muted" />
        )}
        <div className="min-w-0 text-sm">
          <p className="font-medium">
            {candidate.url ? <a href={candidate.url} target="_blank" rel="noreferrer noopener" className="hover:underline">{candidate.name}</a> : candidate.name}
          </p>
          <p className="text-muted-foreground">
            {[candidate.start_year, candidate.publisher, candidate.issue_count != null && t("review.issues", { count: candidate.issue_count })].filter(Boolean).join(" · ")}
          </p>
          <p className="text-xs text-muted-foreground">{PROVIDERS[candidate.provider] ?? candidate.provider}</p>
          {candidate.disqualified && <p className="text-xs text-destructive">{candidate.disqualified}</p>}
        </div>
      </div>
      <div className="space-y-1">
        <p className="text-sm font-semibold tabular-nums">{Math.round(candidate.score * 100)} %</p>
        {Object.entries(candidate.signals ?? {}).map(([signal, value]) => (
          <div key={signal} className="flex items-center gap-2 text-xs">
            <span className="w-16 text-muted-foreground">{t(`review.signals.${signal as "title"}`, { defaultValue: signal })}</span>
            <div className="h-1.5 flex-1 rounded bg-muted" role="meter" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(value * 100)} aria-label={signal}>
              <div className="h-1.5 rounded bg-primary" style={{ width: `${Math.max(0, Math.round(value * 100))}%` }} />
            </div>
            <span className="w-8 text-right tabular-nums">{Math.round(value * 100)}</span>
          </div>
        ))}
      </div>
      {onChoose && (
        <Button className="mt-auto" size="sm" onClick={onChoose} disabled={busy}>
          <Check aria-hidden />
          {shortcut ? t("review.chooseKey", { key: shortcut }) : t("review.choose")}
        </Button>
      )}
    </article>
  );
}

function Regroup({ review, open, onAccept, onReject }: { review: Review; open: boolean; onAccept: () => void; onReject: () => void }) {
  const { t } = useTranslation();
  const moves = Object.values(parsedOf(review).moves ?? {});
  return (
    <div className="space-y-3 rounded-xl border bg-card p-4 text-sm">
      <p>{t("review.regroupIntro")}</p>
      <ul className="list-disc space-y-1 pl-5">
        {moves.map((move) => (
          <li key={move.key}>
            {t("review.regroupMove", { count: move.book_ids.length, title: move.title })} {move.target_series_id ? t("review.existingSeries") : t("review.newSeries")}
          </li>
        ))}
      </ul>
      {open && (
        <div className="flex gap-2">
          <Button onClick={onAccept}>{t("review.regroupAccept")}</Button>
          <Button variant="outline" onClick={onReject}>{t("review.regroupReject")}</Button>
        </div>
      )}
    </div>
  );
}

/** The parsed file names: many apparent wrong matches are parser mistakes, and
 * a parse can be copied as a line for the golden corpus (backend/tests/golden). */
function ParsedNames({ review }: { review: Review }) {
  const { t } = useTranslation();
  const p = parsedOf(review);
  const names = p.parsed_names ?? [];
  if (names.length === 0) return null;
  const golden = (name: string, parsed: Record<string, unknown>) => {
    const expect: Record<string, unknown> = {};
    for (const field of GOLDEN_FIELDS) {
      const value = parsed[field];
      if (value !== null && value !== undefined && value !== false && !(field === "format" && value === "issue")) expect[field] = value;
    }
    return JSON.stringify({ input: name, kind: ["comic", "manga", "book"].includes(p.kind ?? "") ? p.kind : "comic", expect });
  };
  return (
    <details className="rounded-xl border p-3 text-sm">
      <summary className="cursor-pointer text-muted-foreground">{t("review.parsedNames", { count: names.length })}</summary>
      <ul className="mt-2 space-y-2">
        {names.map(({ name, parsed }) => (
          <li key={name} className="flex items-start justify-between gap-2">
            <div className="min-w-0">
              <p className="truncate font-medium">{name}</p>
              <code className="text-xs break-all text-muted-foreground">
                {Object.entries(parsed)
                  .filter(([key, value]) => value !== null && value !== false && key !== "version" && key !== "notes" && !(Array.isArray(value) && value.length === 0))
                  .map(([key, value]) => `${key}=${Array.isArray(value) ? value.join("|") : String(value)}`)
                  .join("  ")}
              </code>
            </div>
            <Button variant="ghost" size="icon-sm" title={t("review.copyGolden")} aria-label={t("review.copyGolden")}
              onClick={() => void navigator.clipboard?.writeText(golden(name, parsed)).then(() => toast.success(t("common.copied")))}>
              <ClipboardCopy aria-hidden />
            </Button>
          </li>
        ))}
      </ul>
    </details>
  );
}
