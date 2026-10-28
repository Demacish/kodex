import { useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { CircleCheck, LayoutGrid, ListChecks, Table2, X } from "lucide-react";
import { useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { api, type Schemas } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Progress } from "@/components/ui/progress";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { format } from "@/i18n";
import { cn } from "@/lib/utils";

import { BookCard, bookNumber, bookTitle } from "./BookCard";
import { CoverGrid } from "./CoverGrid";

type Book = Schemas["BookOut"];
type View = "grid" | "table";
const VIEW_KEY = "kodex-book-view";

export const FORMAT_LABELS: Record<string, string> = {
  epub: "EPUB", pdf: "PDF", cbz: "CBZ", cbr: "CBR", cb7: "CB7", image_folder: "IMG",
};

function storedView(): View {
  try {
    return localStorage.getItem(VIEW_KEY) === "table" ? "table" : "grid";
  } catch {
    return "grid";
  }
}

/** A book grid or table, with selection for marking many as read. */
export function BookList({ books, extraActions, selectionActions }: {
  books: Book[];
  extraActions?: ReactNode;
  selectionActions?: (ids: number[], done: () => void) => ReactNode;
}) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [view, setView] = useState<View>(storedView);
  const [selecting, setSelecting] = useState(false);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const bulk = api.useMutation("post", "/api/me/progress/bulk");

  const changeView = (next: View) => {
    setView(next);
    try {
      localStorage.setItem(VIEW_KEY, next);
    } catch {
      // remembered for this visit only
    }
  };
  const toggle = (id: number) =>
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  const done = () => {
    setSelected(new Set());
    setSelecting(false);
  };
  const markRead = async (finished: boolean) => {
    try {
      await bulk.mutateAsync({ body: { book_ids: [...selected], is_finished: finished } });
      toast.success(finished ? t("list.markedRead") : t("list.markedUnread"));
      done();
      await queryClient.invalidateQueries({ queryKey: ["get", "/api/books"] });
      await queryClient.invalidateQueries({ queryKey: ["get", "/api/series"] });
      await queryClient.invalidateQueries({ queryKey: ["get", "/api/me/continue-reading"] });
    } catch {
      toast.error(t("common.errorGeneric"));
    }
  };

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center justify-end gap-2">
        {extraActions}
        <Button variant="outline" size="sm" onClick={() => (selecting ? done() : setSelecting(true))} aria-pressed={selecting}>
          {selecting ? <X aria-hidden /> : <ListChecks aria-hidden />}
          {selecting ? t("common.cancel") : t("list.select")}
        </Button>
        <Button variant="outline" size="sm" onClick={() => changeView(view === "grid" ? "table" : "grid")}>
          {view === "grid" ? <Table2 aria-hidden /> : <LayoutGrid aria-hidden />}
          {view === "grid" ? t("list.tableView") : t("list.gridView")}
        </Button>
      </div>

      {selecting && (
        <div className="sticky top-16 z-10 mb-4 flex flex-wrap items-center gap-2 rounded-xl border bg-card/95 p-2 shadow-sm backdrop-blur" role="toolbar" aria-label={t("list.selection")}>
          <span className="px-2 text-sm">{t("list.selected", { count: selected.size })}</span>
          <Button size="sm" variant="ghost" onClick={() => setSelected(new Set(books.map((b) => b.id)))}>
            {t("list.selectAll")}
          </Button>
          <span className="ml-auto flex flex-wrap gap-2">
            <Button size="sm" disabled={selected.size === 0 || bulk.isPending} onClick={() => void markRead(true)}>
              {t("list.markRead")}
            </Button>
            <Button size="sm" variant="outline" disabled={selected.size === 0 || bulk.isPending} onClick={() => void markRead(false)}>
              {t("list.markUnread")}
            </Button>
            {selectionActions?.([...selected], done)}
          </span>
        </div>
      )}

      {view === "grid" ? (
        <CoverGrid>
          {books.map((book) => (
            <li key={book.id} className="relative">
              {selecting ? (
                <label className={cn("block cursor-pointer rounded-lg", selected.has(book.id) && "ring-2 ring-primary ring-offset-2 ring-offset-background")}>
                  <span className="pointer-events-none block opacity-90">
                    <BookCard book={book} />
                  </span>
                  <Checkbox
                    checked={selected.has(book.id)}
                    onCheckedChange={() => toggle(book.id)}
                    aria-label={bookTitle(book)}
                    className="absolute top-2 left-2 size-5 bg-background"
                  />
                </label>
              ) : (
                <BookCard book={book} />
              )}
            </li>
          ))}
        </CoverGrid>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              {selecting && <TableHead className="w-8" />}
              <TableHead className="w-16">{t("list.number")}</TableHead>
              <TableHead>{t("list.title")}</TableHead>
              <TableHead className="hidden sm:table-cell">{t("list.format")}</TableHead>
              <TableHead className="hidden md:table-cell">{t("list.pagesColumn")}</TableHead>
              <TableHead className="hidden md:table-cell">{t("list.size")}</TableHead>
              <TableHead className="w-32">{t("list.progress")}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {books.map((book) => (
              <TableRow key={book.id} data-state={selected.has(book.id) ? "selected" : undefined}>
                {selecting && (
                  <TableCell>
                    <Checkbox checked={selected.has(book.id)} onCheckedChange={() => toggle(book.id)} aria-label={bookTitle(book)} />
                  </TableCell>
                )}
                <TableCell className="text-muted-foreground">{bookNumber(t, book) ?? "–"}</TableCell>
                <TableCell className="max-w-0 truncate">
                  <Link to="/books/$bookId" params={{ bookId: book.id }} className="font-medium hover:underline">
                    {bookTitle(book)}
                  </Link>
                </TableCell>
                <TableCell className="hidden sm:table-cell">{FORMAT_LABELS[book.file_format] ?? book.file_format}</TableCell>
                <TableCell className="hidden md:table-cell">{book.page_count ?? "–"}</TableCell>
                <TableCell className="hidden md:table-cell">{format.bytes(book.file_size)}</TableCell>
                <TableCell>
                  {book.progress?.is_finished ? (
                    <span className="inline-flex items-center gap-1 text-xs text-primary-text">
                      <CircleCheck className="size-3.5" aria-hidden />
                      {t("book.finished")}
                    </span>
                  ) : book.progress && book.progress.progress_percent > 0 ? (
                    <Progress value={book.progress.progress_percent} className="h-1.5" aria-label={t("book.progress", { percent: Math.round(book.progress.progress_percent) })} />
                  ) : null}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </div>
  );
}
