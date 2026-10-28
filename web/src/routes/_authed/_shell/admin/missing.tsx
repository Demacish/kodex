import { useQueryClient } from "@tanstack/react-query";
import { createFileRoute, Link } from "@tanstack/react-router";
import { FileQuestion } from "lucide-react";
import { useTranslation } from "react-i18next";

import { api } from "@/api/client";
import { EmptyState, ErrorState, PageHeader } from "@/components/common/states";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { format } from "@/i18n";

export const Route = createFileRoute("/_authed/_shell/admin/missing")({
  component: Missing,
});

/** Books whose file disappeared: hidden from readers until it's back, or shown anyway. */
function Missing() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const books = api.useQuery("get", "/api/books/missing");
  const refresh = () => queryClient.invalidateQueries({ queryKey: ["get", "/api/books/missing"] });
  const hide = api.useMutation("post", "/api/books/{book_id}/hide", { onSuccess: refresh });
  const restore = api.useMutation("post", "/api/books/{book_id}/restore", { onSuccess: refresh });
  return (
    <div>
      <PageHeader title={t("admin.nav.missing")} description={t("missing.intro")} />
      {books.isError ? (
        <ErrorState error={books.error} onRetry={() => void books.refetch()} />
      ) : books.isPending ? (
        <Skeleton className="h-48 rounded-xl" />
      ) : books.data.length === 0 ? (
        <EmptyState icon={FileQuestion} title={t("missing.none")} />
      ) : (
        <ul className="divide-y rounded-xl border bg-card">
          {books.data.map((book) => (
            <li key={book.id} className="flex flex-wrap items-center gap-3 px-4 py-3">
              <div className="min-w-0 flex-1">
                <Link to="/books/$bookId" params={{ bookId: book.id }} className="font-medium hover:text-primary-text">{book.title}</Link>
                <div className="truncate text-xs text-muted-foreground" title={book.file_path}>
                  {[book.library_name, book.series_title, book.file_path].filter(Boolean).join(" · ")}
                </div>
                {book.missing_since && <div className="text-xs text-muted-foreground">{t("missing.since", { when: format.date(book.missing_since) })}</div>}
              </div>
              {book.keep_visible_when_missing ? (
                <Button size="sm" variant="outline" onClick={() => hide.mutate({ params: { path: { book_id: book.id } } })}>{t("missing.hide")}</Button>
              ) : (
                <Button size="sm" variant="outline" onClick={() => restore.mutate({ params: { path: { book_id: book.id } } })}>{t("missing.show")}</Button>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
