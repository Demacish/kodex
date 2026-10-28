import { createFileRoute, Link } from "@tanstack/react-router";
import { lazy, Suspense, useCallback, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { api } from "@/api/client";
import { ErrorState } from "@/components/common/states";
import { bookNumber, bookTitle } from "@/components/library/BookCard";
import { Button } from "@/components/ui/button";
import { idParam } from "@/lib/params";
import { searchSchema, text } from "@/lib/search";
import { ElsewhereNotice } from "@/readers/ElsewhereNotice";
import { LOCATOR, openAt, readerKind } from "@/readers/positions";
import { useProgress, type ProgressUpdate } from "@/readers/useProgress";

const ImageReader = lazy(() => import("@/readers/image/ImageReader").then((m) => ({ default: m.ImageReader })));
const PdfReader = lazy(() => import("@/readers/pdf/PdfReader").then((m) => ({ default: m.PdfReader })));
const EpubReader = lazy(() => import("@/readers/epub/EpubReader").then((m) => ({ default: m.EpubReader })));

const search = searchSchema({ pos: "" }, { pos: text });

export const Route = createFileRoute("/_authed/books/$bookId/read")({
  params: idParam("bookId"),
  validateSearch: search.validate,
  component: ReadPage,
});

function Loading() {
  const { t } = useTranslation();
  return <div className="grid h-dvh place-items-center bg-reader text-sm text-neutral-400">{t("common.loading")}</div>;
}

function ReadPage() {
  const { t } = useTranslation();
  const { bookId } = Route.useParams();
  const { pos } = search.resolve(Route.useSearch());
  const book = api.useQuery("get", "/api/books/{book_id}", { params: { path: { book_id: bookId } } });
  const progress = api.useQuery("get", "/api/books/{book_id}/progress", { params: { path: { book_id: bookId } } }, { staleTime: 0, refetchOnWindowFocus: false });
  const libraryId = book.data?.library_id;
  const library = api.useQuery("get", "/api/libraries/{library_id}", { params: { path: { library_id: libraryId ?? 0 } } }, { enabled: libraryId != null });
  const seriesId = book.data?.series_id;
  const siblings = api.useQuery("get", "/api/books", { params: { query: { series_id: seriesId ?? 0, sort: "number", order: "asc", limit: 1000 } } }, { enabled: seriesId != null });

  if (book.isError) {
    return (
      <div className="mx-auto max-w-lg px-4 py-16">
        <ErrorState error={book.error} onRetry={() => void book.refetch()} />
      </div>
    );
  }
  if (!book.data || progress.isPending || (book.data.series_id != null && siblings.isPending)) return <Loading />;
  return (
    <Reader
      key={bookId}
      book={book.data}
      initial={pos || openAt(readerKind(book.data.file_format) ?? "epub", progress.data, book.data.page_count) || null}
      progress={progress.data ?? null}
      manga={library.data?.library_type === "manga"}
      next={(() => {
        const list = siblings.data ?? [];
        const index = list.findIndex((b) => b.id === bookId);
        return index >= 0 ? list[index + 1] ?? null : null;
      })()}
      fallback={<Button render={<Link to="/books/$bookId" params={{ bookId }} />}>{t("reader.backToBook")}</Button>}
    />
  );
}

type Book = NonNullable<ReturnType<typeof useBookType>>;
function useBookType() {
  return api.useQuery("get", "/api/books/{book_id}", { params: { path: { book_id: 0 } } }).data;
}

function Reader({ book, initial, progress, manga, next, fallback }: {
  book: Book;
  initial: string | null;
  progress: import("@/readers/useProgress").Progress | null;
  manga: boolean;
  next: Book | null;
  fallback: React.ReactNode;
}) {
  const { t } = useTranslation();
  const kind = readerKind(book.file_format);
  const sync = useProgress(book.id, progress, kind ? LOCATOR[kind] : null);
  const [jump, setJump] = useState<{ position: string; at: number } | null>(null);
  const title = bookTitle(book);
  const subtitle = useMemo(() => bookNumber(t, book), [t, book]);
  const onProgress = useCallback((update: ProgressUpdate) => sync.save(update), [sync]);
  const elsewhere = sync.elsewhere && kind ? openAt(kind, sync.elsewhere, book.page_count) : null;
  const elsewhereLabel = (chapter?: string | null) =>
    chapter ?? (kind === "image" ? t("reader.pageShort", { page: Number(elsewhere ?? 0) + 1 }) : kind === "pdf" ? t("reader.pageShort", { page: Number(elsewhere ?? 1) }) : t("reader.laterPosition"));

  let reader: React.ReactNode;
  if (kind === "image") {
    reader = (
      <ImageReader
        book={book}
        title={title}
        subtitle={subtitle}
        manga={manga}
        initialPage={Number.parseInt(initial ?? "0", 10) || 0}
        jump={jump ? { page: Number.parseInt(jump.position, 10) || 0, at: jump.at } : null}
        next={next}
        onProgress={onProgress}
      />
    );
  } else if (kind === "pdf") {
    reader = (
      <PdfReader
        book={book}
        title={title}
        subtitle={subtitle}
        initialPage={Number.parseInt(initial ?? "1", 10) || 1}
        jump={jump ? { page: Number.parseInt(jump.position, 10) || 1, at: jump.at } : null}
        onProgress={onProgress}
      />
    );
  } else if (kind === "epub") {
    reader = <EpubReader book={book} title={title} subtitle={subtitle} initial={initial} jump={jump} onProgress={onProgress} />;
  } else {
    reader = (
      <div className="grid h-dvh place-items-center gap-4 bg-reader text-neutral-300">
        <p>{t("reader.unsupported")}</p>
        {fallback}
      </div>
    );
  }

  return (
    <>
      <Suspense fallback={<Loading />}>{reader}</Suspense>
      {sync.elsewhere && (
        <ElsewhereNotice
          progress={sync.elsewhere}
          label={elsewhereLabel(sync.elsewhere.chapter)}
          onJump={() => {
            if (elsewhere) setJump({ position: elsewhere, at: Date.now() });
            sync.dismiss();
          }}
          onDismiss={sync.dismiss}
        />
      )}
    </>
  );
}
