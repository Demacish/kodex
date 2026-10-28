import { createFileRoute, Link } from "@tanstack/react-router";
import { Search as SearchIcon } from "lucide-react";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import { api } from "@/api/client";
import { CoverGridSkeleton, EmptyState, ErrorState, PageHeader } from "@/components/common/states";
import { Cover } from "@/components/library/Cover";
import { CoverGrid } from "@/components/library/CoverGrid";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { oneOf, searchSchema, text } from "@/lib/search";

const MODES = ["books", "fulltext"] as const;
const search = searchSchema({ q: "", mode: "books" as (typeof MODES)[number] }, { q: text, mode: oneOf(MODES) });

export const Route = createFileRoute("/_authed/_shell/search")({
  validateSearch: search.validate,
  component: SearchPage,
});

/** Meilisearch marks hits with <mark>; everything else is shown as text. */
const ENTITIES: Record<string, string> = { "&lt;": "<", "&gt;": ">", "&quot;": '"', "&#x27;": "'", "&amp;": "&" };

/** The book's own text, which the server sends escaped. */
function unescape(text: string): string {
  return text.replace(/&(lt|gt|quot|#x27|amp);/g, (entity) => ENTITIES[entity] ?? entity);
}

/** A hit's snippet: escaped text with the hit in <mark>, shown as text, never as HTML. */
function Snippet({ html }: { html: string }) {
  const parts = html.split(/(<mark>.*?<\/mark>)/g);
  return (
    <p className="mt-1 text-sm text-muted-foreground">
      {parts.map((part, i) =>
        part.startsWith("<mark>") ? (
          <mark key={i} className="rounded bg-primary/25 px-0.5 text-foreground">{unescape(part.slice(6, -7))}</mark>
        ) : (
          <span key={i}>{unescape(part)}</span>
        ),
      )}
    </p>
  );
}

function SearchPage() {
  const { t } = useTranslation();
  const { q, mode } = search.resolve(Route.useSearch());
  const navigate = Route.useNavigate();
  const [draft, setDraft] = useState(q);
  const books = api.useQuery("get", "/api/search/books", { params: { query: { q, limit: 60 } } }, { enabled: !!q && mode === "books" });
  const fulltext = api.useQuery("get", "/api/search/fulltext", { params: { query: { q, limit: 50 } } }, { enabled: !!q && mode === "fulltext" });
  const query = mode === "books" ? books : fulltext;

  const submit = (event: FormEvent) => {
    event.preventDefault();
    void navigate({ search: search.update({ q: draft.trim() }) });
  };

  return (
    <div>
      <PageHeader title={t("nav.search")} />
      <form role="search" onSubmit={submit} className="mb-4 flex max-w-xl gap-2">
        <Input type="search" value={draft} onChange={(e) => setDraft(e.target.value)} placeholder={t("searchPage.placeholder")} aria-label={t("common.search")} autoFocus />
        <Button type="submit">
          <SearchIcon aria-hidden />
          {t("common.search")}
        </Button>
      </form>
      <ToggleGroup value={[mode]} onValueChange={(v: string[]) => v[0] && navigate({ search: search.update({ mode: v[0] as (typeof MODES)[number] }) })} variant="outline" size="sm" className="mb-6">
        <ToggleGroupItem value="books">{t("searchPage.books")}</ToggleGroupItem>
        <ToggleGroupItem value="fulltext">{t("searchPage.fulltext")}</ToggleGroupItem>
      </ToggleGroup>

      {!q ? (
        <p className="text-sm text-muted-foreground">{t("searchPage.prompt")}</p>
      ) : query.isPending ? (
        <CoverGridSkeleton count={6} />
      ) : query.isError ? (
        <ErrorState error={t("searchPage.failed")} onRetry={() => void query.refetch()} />
      ) : mode === "books" ? (
        books.data?.length ? (
          <CoverGrid>
            {books.data.map((hit) => (
              <li key={hit.book_id}>
                <Link to="/books/$bookId" params={{ bookId: hit.book_id }} className="group block rounded-lg">
                  <div className="transition-transform group-hover:-translate-y-0.5">
                    <Cover bookId={hit.book_id} alt="" className="shadow-sm ring-1 ring-foreground/5" />
                  </div>
                  <div className="mt-2 line-clamp-2 text-sm font-medium">{hit.title}</div>
                  {hit.series_title && <div className="truncate text-xs text-muted-foreground">{hit.series_title}</div>}
                </Link>
              </li>
            ))}
          </CoverGrid>
        ) : (
          <EmptyState icon={SearchIcon} title={t("searchPage.none", { q })} />
        )
      ) : fulltext.data?.length ? (
        <ul className="space-y-3">
          {fulltext.data.map((hit, i) => (
            <li key={`${hit.book_id}-${hit.position}-${i}`} className="rounded-xl border bg-card p-4">
              <Link to="/books/$bookId/read" params={{ bookId: hit.book_id }} search={{ pos: hit.position }} className="font-medium hover:text-primary-text">
                {hit.title}
              </Link>
              <Snippet html={hit.snippet} />
            </li>
          ))}
        </ul>
      ) : (
        <EmptyState icon={SearchIcon} title={t("searchPage.none", { q })}>{t("searchPage.fulltextHint")}</EmptyState>
      )}
    </div>
  );
}
