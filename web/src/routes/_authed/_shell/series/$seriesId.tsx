import { useQueryClient } from "@tanstack/react-query";
import { createFileRoute, Link, notFound } from "@tanstack/react-router";
import { Bell, BellOff, ChevronLeft, FileJson, Play, RefreshCw } from "lucide-react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { api } from "@/api/client";
import { CoverGridSkeleton, ErrorState } from "@/components/common/states";
import { BookList } from "@/components/library/BookList";
import { bookNumber, bookTitle } from "@/components/library/BookCard";
import { Cover } from "@/components/library/Cover";
import { ExpandableText } from "@/components/common/ExpandableText";
import { ListControls, Pager, READ_STATUSES, type ReadStatus } from "@/components/library/ListControls";
import { useFollow } from "@/components/library/SeriesCard";
import { MissingIssues } from "@/components/library/MissingIssues";
import { SeriesTrackers } from "@/components/library/SeriesTrackers";
import { MergeDialog, MoveButton, SplitButton } from "@/components/admin/SeriesOps";
import { SeriesPeers } from "@/components/admin/SeriesPeers";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { useAccount } from "@/lib/account";
import { numberGaps } from "@/lib/numbers";
import { idParam } from "@/lib/params";
import { count, oneOf, searchSchema } from "@/lib/search";

const SORTS = ["number", "title", "added_at", "updated_at"] as const;
const LIMIT = 200;

const search = searchSchema(
  { sort: "number" as (typeof SORTS)[number], order: "asc" as "asc" | "desc", status: "all" as ReadStatus, offset: 0 },
  { sort: oneOf(SORTS), order: oneOf(["asc", "desc"]), status: oneOf(READ_STATUSES), offset: count },
);
type Search = ReturnType<typeof search.resolve>;

export const Route = createFileRoute("/_authed/_shell/series/$seriesId")({
  validateSearch: search.validate,
  params: idParam("seriesId"),
  component: SeriesPage,
});

function SeriesPage() {
  const { t } = useTranslation();
  const account = useAccount();
  const queryClient = useQueryClient();
  const { seriesId } = Route.useParams();
  const state = search.resolve(Route.useSearch());
  const navigate = Route.useNavigate();
  const set = (next: Partial<Search>) => void navigate({ search: search.update(next), replace: true });

  const series = api.useQuery("get", "/api/series/{series_id}", { params: { path: { series_id: seriesId } } });
  const books = api.useQuery("get", "/api/books", {
    params: { query: { series_id: seriesId, sort: state.sort, order: state.order, read_status: state.status, limit: LIMIT + 1, offset: state.offset } },
  });
  // Reading order and gaps look at the whole series, whatever the filter.
  const all = api.useQuery("get", "/api/books", { params: { query: { series_id: seriesId, sort: "number", order: "asc", limit: 1000 } } });
  const follow = useFollow(series.data ?? { id: seriesId, is_following: false });
  const exportJson = api.useMutation("post", "/api/series/{series_id}/export");
  const rematch = api.useMutation("post", "/api/matching/series/{series_id}/match");

  if (series.isError) {
    if ((series.error as { detail?: string } | null)?.detail === "Series not found") throw notFound();
    return <ErrorState error={series.error} onRetry={() => void series.refetch()} />;
  }
  if (!series.data) return <CoverGridSkeleton />;
  const s = series.data;
  const page = books.data?.slice(0, LIMIT) ?? [];
  const issues = page.filter((book) => book.edition_type !== "collected");
  const collected = page.filter((book) => book.edition_type === "collected");
  const everything = all.data ?? [];
  const next = everything.find((book) => book.progress && !book.progress.is_finished && book.progress.progress_percent > 0)
    ?? everything.find((book) => !book.progress?.is_finished);
  const gaps = numberGaps(everything.filter((book) => book.edition_type !== "collected").map((book) => book.number));
  const readPercent = s.book_count ? (s.read_count / s.book_count) * 100 : 0;
  const coverId = s.cover_book_id;

  const adminActions = account.is_admin
    ? (ids: number[], done: () => void) => (
        <>
          <SplitButton seriesId={s.id} bookIds={ids} done={done} />
          <MoveButton libraryId={s.library_id} seriesId={s.id} bookIds={ids} done={done} />
        </>
      )
    : undefined;

  const doExport = async () => {
    try {
      await exportJson.mutateAsync({ params: { path: { series_id: s.id } } });
      toast.success(t("series.exported"));
      await queryClient.invalidateQueries({ queryKey: ["get", "/api/series/{series_id}"] });
    } catch {
      toast.error(t("common.errorGeneric"));
    }
  };
  const doRematch = async () => {
    try {
      await rematch.mutateAsync({ params: { path: { series_id: s.id } } });
      toast.success(t("series.rematchQueued"));
    } catch {
      toast.error(t("common.errorGeneric"));
    }
  };

  return (
    <div>
      <section className="relative -mx-4 -mt-6 mb-8 overflow-hidden px-4 pt-6 pb-8 md:-mx-6 md:px-6">
        {coverId != null && (
          <div aria-hidden className="absolute inset-0 -z-10">
            <img src={`/api/books/${coverId}/cover?size=small`} alt="" className="h-full w-full scale-110 object-cover opacity-30 blur-3xl dark:opacity-25" />
            <div className="absolute inset-0 bg-gradient-to-b from-background/40 via-background/70 to-background" />
          </div>
        )}
        <Link to="/libraries/$libraryId" params={{ libraryId: s.library_id }} className="mb-3 inline-flex items-center py-1 text-sm text-muted-foreground hover:text-foreground">
          <ChevronLeft className="size-4" aria-hidden />
          {t("series.backToLibrary")}
        </Link>
        {/* As on a book's page: on a phone the cover beside the title, the rest below both. */}
        <div className="grid grid-cols-[7rem_minmax(0,1fr)] grid-rows-[auto_1fr] gap-x-4 gap-y-4 sm:grid-cols-[12rem_minmax(0,1fr)] sm:gap-x-6">
          <Cover bookId={coverId} alt={s.title} size="large" eager className="w-full shadow-xl ring-1 ring-foreground/10 sm:row-span-2" />
          <div className="min-w-0 space-y-3 self-center sm:self-start">
            <div>
              <h1 className="text-2xl font-semibold tracking-tight text-balance sm:text-3xl">{s.title}</h1>
              <p className="mt-1 text-sm text-muted-foreground">
                {[s.publisher, s.start_year, s.status && t(`series.statuses.${s.status as "ongoing"}`, { defaultValue: s.status })]
                  .filter(Boolean)
                  .join(" · ")}
              </p>
            </div>
            {(s.new_release_available || (account.is_admin && s.match_status && s.match_status !== "unmatched")) && (
              <div className="flex flex-wrap items-center gap-2">
                {s.new_release_available && <Badge>{t("series.newRelease")}</Badge>}
                {account.is_admin && s.match_status && s.match_status !== "unmatched" && (
                  <Badge variant={s.match_status === "review" ? "destructive" : "secondary"}>{t(`series.match.${s.match_status as "auto"}`, { defaultValue: s.match_status })}</Badge>
                )}
              </div>
            )}
          </div>
          <div className="col-span-2 min-w-0 space-y-3 sm:col-span-1 sm:col-start-2">
            <div className="max-w-sm">
              <div className="mb-1 flex justify-between text-xs text-muted-foreground">
                <span>{t("series.readCount", { read: s.read_count, count: s.book_count })}</span>
                <span>{Math.round(readPercent)} %</span>
              </div>
              <Progress value={readPercent} className="h-1.5" aria-label={t("series.readCount", { read: s.read_count, count: s.book_count })} />
            </div>
            {s.summary && <ExpandableText text={s.summary} className="max-w-3xl text-sm leading-relaxed text-muted-foreground" />}
            <div className="flex flex-wrap gap-2 pt-1">
              {next && (
                <Button className="max-sm:w-full" render={<Link to="/books/$bookId/read" params={{ bookId: next.id }} />}>
                  <Play className="fill-current" strokeWidth={0} aria-hidden />
                  {next.progress && next.progress.progress_percent > 0
                    ? t("series.continue", { what: bookNumber(t, next) ?? bookTitle(next) })
                    : t("series.start", { what: bookNumber(t, next) ?? bookTitle(next) })}
                </Button>
              )}
              <Button variant="outline" onClick={() => void follow.toggle()} disabled={follow.pending} aria-pressed={s.is_following}>
                {s.is_following ? <Bell aria-hidden /> : <BellOff aria-hidden />}
                {s.is_following ? t("series.following") : t("series.follow")}
              </Button>
              <SeriesTrackers seriesId={s.id} title={s.title} />
              {account.is_admin && (
                <>
                  <Button variant="ghost" onClick={() => void doRematch()} disabled={rematch.isPending}>
                    <RefreshCw aria-hidden />
                    {t("series.rematch")}
                  </Button>
                  <Button variant="ghost" onClick={() => void doExport()} disabled={exportJson.isPending} title={t("series.exportHint")}>
                    <FileJson aria-hidden />
                    {t("series.export")}
                  </Button>
                  <MergeDialog libraryId={s.library_id} seriesId={s.id} />
                </>
              )}
            </div>
            <MissingIssues seriesId={s.id} gaps={gaps} />
          </div>
        </div>
      </section>

      {account.is_admin && <SeriesPeers seriesId={s.id} />}
      <ListControls
        sorts={SORTS}
        state={{ sort: state.sort, order: state.order, status: state.status }}
        onChange={(change) => set({ offset: 0, ...change })}
      />
      {books.isPending ? (
        <CoverGridSkeleton />
      ) : books.isError ? (
        <ErrorState error={books.error} onRetry={() => void books.refetch()} />
      ) : page.length === 0 ? (
        <p className="text-sm text-muted-foreground">{state.status === "all" ? t("series.noBooks") : t("list.noMatches")}</p>
      ) : collected.length === 0 || issues.length === 0 ? (
        <BookList books={page} selectionActions={adminActions} />
      ) : (
        <div className="space-y-10">
          <section aria-labelledby="issues-heading">
            <h2 id="issues-heading" className="mb-2 text-sm font-semibold text-muted-foreground">{t("series.issues", { count: issues.length })}</h2>
            <BookList books={issues} selectionActions={adminActions} />
          </section>
          <section aria-labelledby="collected-heading">
            <h2 id="collected-heading" className="mb-2 text-sm font-semibold text-muted-foreground">{t("series.collected", { count: collected.length })}</h2>
            <BookList books={collected} selectionActions={adminActions} />
          </section>
        </div>
      )}
      <Pager offset={state.offset} limit={LIMIT} hasMore={(books.data?.length ?? 0) > LIMIT} onChange={(offset) => set({ offset })} />
    </div>
  );
}
