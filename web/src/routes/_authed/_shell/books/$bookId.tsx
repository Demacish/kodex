import { createFileRoute, Link } from "@tanstack/react-router";
import { ChevronLeft, Download, Play, Send } from "lucide-react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { api, errorMessage } from "@/api/client";
import { ExpandableText } from "@/components/common/ExpandableText";
import { ErrorState } from "@/components/common/states";
import { bookNumber, bookTitle } from "@/components/library/BookCard";
import { FORMAT_LABELS } from "@/components/library/BookList";
import { Cover } from "@/components/library/Cover";
import { ManualMatchDialog } from "@/components/library/ManualMatchDialog";
import { MetadataEditDialog } from "@/components/library/MetadataEditDialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { Skeleton } from "@/components/ui/skeleton";
import { format } from "@/i18n";
import { useAccount } from "@/lib/account";
import { idParam } from "@/lib/params";

const DOWNLOADABLE = ["epub", "pdf", "cbz", "cbr", "cb7"];

export const Route = createFileRoute("/_authed/_shell/books/$bookId")({
  params: idParam("bookId"),
  component: BookPage,
});

function BookPage() {
  const { t } = useTranslation();
  const account = useAccount();
  const { bookId } = Route.useParams();
  const book = api.useQuery("get", "/api/books/{book_id}", { params: { path: { book_id: bookId } } });
  const progress = api.useQuery("get", "/api/books/{book_id}/progress", { params: { path: { book_id: bookId } } });
  const kindle = api.useMutation("post", "/api/books/{book_id}/send-to-kindle");

  if (book.isError) return <ErrorState error={book.error} onRetry={() => void book.refetch()} />;
  if (!book.data) {
    return (
      <div className="flex flex-col gap-6 sm:flex-row">
        <Skeleton className="aspect-[2/3] w-48 rounded-lg" />
        <div className="flex-1 space-y-3">
          <Skeleton className="h-8 w-2/3" />
          <Skeleton className="h-4 w-1/3" />
        </div>
      </div>
    );
  }
  const b = book.data;
  const meta = b.book_metadata;
  const title = bookTitle(b);
  const p = progress.data;
  const started = p && p.progress_percent > 0 && !p.is_finished;
  const number = bookNumber(t, b);

  const sendToKindle = async () => {
    try {
      await kindle.mutateAsync({ params: { path: { book_id: b.id } } });
      toast.success(t("book.kindleSent"));
    } catch (error) {
      toast.error(errorMessage(error, t("book.kindleFailed")));
    }
  };

  return (
    <div>
      {b.series_id != null ? (
        <Link to="/series/$seriesId" params={{ seriesId: b.series_id }} className="mb-3 inline-flex items-center py-1 text-sm text-muted-foreground hover:text-foreground">
          <ChevronLeft className="size-4" aria-hidden />
          {t("book.backToSeries")}
        </Link>
      ) : (
        <Link to="/libraries/$libraryId" params={{ libraryId: b.library_id }} className="mb-3 inline-flex items-center py-1 text-sm text-muted-foreground hover:text-foreground">
          <ChevronLeft className="size-4" aria-hidden />
          {t("series.backToLibrary")}
        </Link>
      )}
      {/* On a phone the cover sits beside the title and the rest runs below both; from sm the cover has a column of its own. */}
      <div className="grid grid-cols-[7rem_minmax(0,1fr)] grid-rows-[auto_1fr] gap-x-4 gap-y-5 sm:grid-cols-[14rem_minmax(0,1fr)] sm:gap-x-8">
        <Cover bookId={b.id} alt={title} size="large" eager className="w-full shadow-xl ring-1 ring-foreground/10 sm:row-span-2" />
        <div className="min-w-0 self-center sm:self-start">
          {number && <p className="text-sm font-medium text-primary-text">{number}</p>}
          <h1 className="text-2xl font-semibold tracking-tight text-balance sm:text-3xl">{title}</h1>
          {meta && meta.authors.length > 0 && <p className="mt-1 text-muted-foreground">{meta.authors.join(", ")}</p>}
        </div>
        <div className="col-span-2 min-w-0 space-y-4 sm:col-span-1 sm:col-start-2">
          {account.is_admin && (
            <div className="flex flex-wrap gap-2">
              <ManualMatchDialog book={b} initialQuery={title} />
              {meta && <MetadataEditDialog book={b} />}
            </div>
          )}
          {b.missing_since && (
            <p className="text-sm text-destructive">{t("book.missing", { since: format.date(b.missing_since) })}</p>
          )}
          {meta?.source === "manual" && <Badge variant="secondary">{t("book.editedByHand")}</Badge>}
          <div className="flex flex-wrap gap-2">
            <Badge variant="outline">{FORMAT_LABELS[b.file_format] ?? b.file_format}</Badge>
            <Badge variant="outline">{format.bytes(b.file_size)}</Badge>
            {b.page_count != null && <Badge variant="outline">{t("book.pages", { count: b.page_count })}</Badge>}
            {meta?.published_year && <Badge variant="outline">{meta.published_year}</Badge>}
            {meta?.publisher && <Badge variant="outline">{meta.publisher}</Badge>}
            {meta?.language && <Badge variant="outline">{meta.language}</Badge>}
          </div>
          {meta && meta.genres.length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {meta.genres.map((genre) => (
                <Badge key={genre} variant="secondary">{genre}</Badge>
              ))}
            </div>
          )}
          {meta?.summary && <ExpandableText text={meta.summary} lines={6} className="max-w-3xl text-sm leading-relaxed text-muted-foreground" />}
          {started && (
            <div className="max-w-sm">
              <div className="mb-1 text-xs text-muted-foreground">{t("book.progress", { percent: Math.round(p.progress_percent) })}</div>
              <Progress value={p.progress_percent} className="h-1.5" />
            </div>
          )}
          <div className="flex flex-wrap gap-2 pt-2">
            <Button size="lg" className="max-sm:w-full" render={<Link to="/books/$bookId/read" params={{ bookId: b.id }} />}>
              <Play className="fill-current" strokeWidth={0} aria-hidden />
              {started ? t("book.continue", { percent: Math.round(p.progress_percent) }) : p?.is_finished ? t("book.readAgain") : t("book.read")}
            </Button>
            {DOWNLOADABLE.includes(b.file_format) && (
              <>
                <Button size="lg" variant="outline" className="max-sm:flex-1" render={<a href={`/api/books/${b.id}/file`} download />}>
                  <Download aria-hidden />
                  {t("book.download")}
                </Button>
                <Button size="lg" variant="outline" className="max-sm:flex-1" onClick={() => void sendToKindle()} disabled={kindle.isPending}>
                  <Send aria-hidden />
                  {t("book.sendToKindle")}
                </Button>
              </>
            )}
          </div>
          <div className="pt-2 text-xs text-muted-foreground">
            <div className="font-medium text-foreground">{t("book.file")}</div>
            <div className="break-all font-mono select-all">{b.file_path}</div>
          </div>
        </div>
      </div>
    </div>
  );
}
