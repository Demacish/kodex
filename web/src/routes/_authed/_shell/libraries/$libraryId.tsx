import { createFileRoute } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";

import { api } from "@/api/client";
import { CoverGridSkeleton, EmptyState, ErrorState, PageHeader } from "@/components/common/states";
import { AlphabetBar } from "@/components/library/AlphabetBar";
import { BookList } from "@/components/library/BookList";
import { CoverGrid } from "@/components/library/CoverGrid";
import { ListControls, Pager, READ_STATUSES, type ReadStatus } from "@/components/library/ListControls";
import { SeriesCard } from "@/components/library/SeriesCard";
import { idParam } from "@/lib/params";
import { count, oneOf, searchSchema } from "@/lib/search";

const SERIES_SORTS = ["title", "added_at"] as const;
const BOOK_SORTS = ["number", "title", "added_at", "updated_at"] as const;
const LIMIT = 60;

const search = searchSchema(
  { s_sort: "title" as (typeof SERIES_SORTS)[number], s_order: "asc" as "asc" | "desc", s_status: "all" as ReadStatus, s_offset: 0,
    b_sort: "number" as (typeof BOOK_SORTS)[number], b_order: "asc" as "asc" | "desc", b_status: "all" as ReadStatus, b_offset: 0 },
  { s_sort: oneOf(SERIES_SORTS), s_order: oneOf(["asc", "desc"]), s_status: oneOf(READ_STATUSES), s_offset: count,
    b_sort: oneOf(BOOK_SORTS), b_order: oneOf(["asc", "desc"]), b_status: oneOf(READ_STATUSES), b_offset: count },
);
type Search = ReturnType<typeof search.resolve>;

export const Route = createFileRoute("/_authed/_shell/libraries/$libraryId")({
  validateSearch: search.validate,
  params: idParam("libraryId"),
  component: LibraryPage,
});

function LibraryPage() {
  const { t } = useTranslation();
  const { libraryId } = Route.useParams();
  const state = search.resolve(Route.useSearch());
  const navigate = Route.useNavigate();
  const set = (next: Partial<Search>) => void navigate({ search: search.update(next), replace: true });

  const library = api.useQuery("get", "/api/libraries/{library_id}", { params: { path: { library_id: libraryId } } });
  const series = api.useQuery("get", "/api/series", {
    params: { query: { library_id: libraryId, sort: state.s_sort, order: state.s_order, read_status: state.s_status, limit: LIMIT + 1, offset: state.s_offset } },
  });
  const books = api.useQuery("get", "/api/books", {
    params: { query: { library_id: libraryId, root_only: true, sort: state.b_sort, order: state.b_order, read_status: state.b_status, limit: LIMIT + 1, offset: state.b_offset } },
  });

  if (library.isError) return <ErrorState error={library.error} onRetry={() => void library.refetch()} />;
  const seriesPage = series.data?.slice(0, LIMIT) ?? [];
  const booksPage = books.data?.slice(0, LIMIT) ?? [];
  const filtered = state.s_status !== "all" || state.b_status !== "all";
  const nothing = series.data && books.data && seriesPage.length === 0 && booksPage.length === 0 && state.s_offset === 0 && state.b_offset === 0;

  return (
    <div>
      <PageHeader title={library.data?.name ?? "…"} description={library.data && t(`library.types.${library.data.library_type as "comics"}`)} />
      {series.isPending || books.isPending ? (
        <CoverGridSkeleton />
      ) : nothing && !filtered ? (
        <EmptyState title={t("library.empty")}>{t("library.emptyText")}</EmptyState>
      ) : (
        <>
          {(seriesPage.length > 0 || state.s_offset > 0 || state.s_status !== "all") && (
            <section className="mb-12" aria-labelledby="series-heading">
              <h2 id="series-heading" className="mb-3 text-lg font-semibold tracking-tight">{t("library.series")}</h2>
              <ListControls
                sorts={SERIES_SORTS}
                state={{ sort: state.s_sort, order: state.s_order, status: state.s_status }}
                onChange={(next) => set({ s_offset: 0, ...(next.sort && { s_sort: next.sort }), ...(next.order && { s_order: next.order }), ...(next.status && { s_status: next.status }) })}
              />
              {state.s_sort === "title" && state.s_order === "asc" && state.s_status === "all" && (
                <AlphabetBar libraryId={libraryId} limit={LIMIT} offset={state.s_offset} onJump={(offset) => set({ s_offset: offset })} />
              )}
              {series.isError ? (
                <ErrorState error={series.error} onRetry={() => void series.refetch()} />
              ) : seriesPage.length === 0 ? (
                <p className="text-sm text-muted-foreground">{t("list.noMatches")}</p>
              ) : (
                <CoverGrid>
                  {seriesPage.map((item) => (
                    <li key={item.id}>
                      <SeriesCard series={item} />
                    </li>
                  ))}
                </CoverGrid>
              )}
              <Pager offset={state.s_offset} limit={LIMIT} hasMore={(series.data?.length ?? 0) > LIMIT} onChange={(offset) => set({ s_offset: offset })} />
            </section>
          )}
          {(booksPage.length > 0 || state.b_offset > 0 || state.b_status !== "all") && (
            <section aria-labelledby="books-heading">
              <h2 id="books-heading" className="mb-3 text-lg font-semibold tracking-tight">{t("library.books")}</h2>
              <ListControls
                sorts={BOOK_SORTS}
                state={{ sort: state.b_sort, order: state.b_order, status: state.b_status }}
                onChange={(next) => set({ b_offset: 0, ...(next.sort && { b_sort: next.sort }), ...(next.order && { b_order: next.order }), ...(next.status && { b_status: next.status }) })}
              />
              {books.isError ? (
                <ErrorState error={books.error} onRetry={() => void books.refetch()} />
              ) : booksPage.length === 0 ? (
                <p className="text-sm text-muted-foreground">{t("list.noMatches")}</p>
              ) : (
                <BookList books={booksPage} />
              )}
              <Pager offset={state.b_offset} limit={LIMIT} hasMore={(books.data?.length ?? 0) > LIMIT} onChange={(offset) => set({ b_offset: offset })} />
            </section>
          )}
        </>
      )}
    </div>
  );
}
