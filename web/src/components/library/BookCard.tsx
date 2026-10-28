import { Link } from "@tanstack/react-router";
import { CircleCheck } from "lucide-react";
import { useTranslation } from "react-i18next";

import type { Schemas } from "@/api/client";
import { Progress } from "@/components/ui/progress";
import { cn } from "@/lib/utils";

import { Cover } from "./Cover";

type Book = Schemas["BookOut"];

export function bookTitle(book: Pick<Book, "book_metadata" | "file_path">): string {
  return book.book_metadata?.title ?? book.file_path.split("/").pop() ?? book.file_path;
}

export function bookNumber(t: (key: "book.volume" | "book.issue", options: { number: string }) => string,
                           book: Pick<Book, "number" | "edition_type">): string | null {
  if (book.number == null) return null;
  const number = Number.isInteger(book.number) ? String(book.number) : String(book.number);
  return book.edition_type === "collected" ? t("book.volume", { number }) : t("book.issue", { number });
}

export function BookCard({ book, className, subtitle }: { book: Book; className?: string; subtitle?: string }) {
  const { t } = useTranslation();
  const title = bookTitle(book);
  const progress = book.progress;
  const number = subtitle ?? bookNumber(t, book);
  return (
    <Link to="/books/$bookId" params={{ bookId: book.id }} className={cn("group block rounded-lg", className)}>
      <div className="relative transition-transform duration-200 group-hover:-translate-y-0.5">
        <Cover bookId={book.id} alt="" className="shadow-sm ring-1 ring-foreground/5" />
        {progress?.is_finished ? (
          <span className="absolute top-1.5 right-1.5 rounded-full bg-primary p-0.5 text-primary-foreground shadow-sm">
            <CircleCheck className="size-3.5" aria-hidden />
            <span className="sr-only">{t("book.finished")}</span>
          </span>
        ) : progress && progress.progress_percent > 0 ? (
          <Progress
            value={progress.progress_percent}
            aria-label={t("book.progress", { percent: Math.round(progress.progress_percent) })}
            className="absolute inset-x-2 bottom-2 h-1"
          />
        ) : null}
      </div>
      <div className="mt-2 line-clamp-2 text-sm leading-snug font-medium">{title}</div>
      {number && <div className="text-xs text-muted-foreground">{number}</div>}
    </Link>
  );
}
