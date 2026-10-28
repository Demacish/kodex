import { createFileRoute, Link } from "@tanstack/react-router";
import { Copy } from "lucide-react";
import { useTranslation } from "react-i18next";

import { api, type Schemas } from "@/api/client";
import { EmptyState, ErrorState, PageHeader } from "@/components/common/states";
import { Cover } from "@/components/library/Cover";
import { Skeleton } from "@/components/ui/skeleton";
import { format } from "@/i18n";

export const Route = createFileRoute("/_authed/_shell/admin/duplicates")({
  component: Duplicates,
});

function Group({ books, exact }: { books: Schemas["DuplicateBookOut"][]; exact: boolean }) {
  const { t } = useTranslation();
  return (
    <li className="rounded-xl border bg-card p-3">
      <ul className="flex gap-4 overflow-x-auto">
        {books.map((book, i) => (
          <li key={book.id} className="w-36 shrink-0">
            <Link to="/books/$bookId" params={{ bookId: book.id }} className="block">
              <Cover bookId={book.id} alt="" size="small" />
              <div className="mt-1 line-clamp-2 text-xs font-medium">{book.title ?? book.file_path.split("/").pop()}</div>
            </Link>
            <div className="truncate text-[11px] text-muted-foreground" title={book.file_path}>{book.file_path}</div>
            <div className="text-[11px] text-muted-foreground">
              {book.file_format.toUpperCase()} · {format.bytes(book.file_size)}
              {exact && i === 0 && ` · ${t("duplicates.original")}`}
            </div>
          </li>
        ))}
      </ul>
    </li>
  );
}

/** Exact duplicates (the same pages) and similar books (same number, nearly the same cover). */
function Duplicates() {
  const { t } = useTranslation();
  const groups = api.useQuery("get", "/api/library/duplicates");
  return (
    <div>
      <PageHeader title={t("admin.nav.duplicates")} description={t("duplicates.intro")} />
      {groups.isError ? (
        <ErrorState error={groups.error} onRetry={() => void groups.refetch()} />
      ) : groups.isPending ? (
        <Skeleton className="h-48 rounded-xl" />
      ) : groups.data.exact.length === 0 && groups.data.similar.length === 0 ? (
        <EmptyState icon={Copy} title={t("duplicates.none")} />
      ) : (
        <div className="space-y-8">
          {(["exact", "similar"] as const).map((kind) =>
            groups.data[kind].length > 0 ? (
              <section key={kind} aria-labelledby={`dup-${kind}`}>
                <h2 id={`dup-${kind}`} className="mb-1 text-lg font-semibold">{t(`duplicates.${kind}`, { count: groups.data[kind].length })}</h2>
                <p className="mb-3 text-sm text-muted-foreground">{t(`duplicates.${kind}Hint`)}</p>
                <ul className="space-y-3">{groups.data[kind].map((books) => <Group key={books.map((b) => b.id).join("-")} books={books} exact={kind === "exact"} />)}</ul>
              </section>
            ) : null,
          )}
        </div>
      )}
    </div>
  );
}
