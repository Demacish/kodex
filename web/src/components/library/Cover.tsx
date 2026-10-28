import { BookOpen } from "lucide-react";
import { useState } from "react";

import { cn } from "@/lib/utils";

export type CoverSize = "small" | "medium" | "large";

/** A book's cover from the server (WebP in three sizes), or a placeholder. */
export function Cover({ bookId, alt, size = "medium", className, eager = false }: {
  bookId: number | null | undefined;
  alt: string;
  size?: CoverSize;
  className?: string;
  eager?: boolean;
}) {
  const [failedFor, setFailedFor] = useState<number | null>(null);
  const failed = bookId == null || failedFor === bookId;
  return (
    <div className={cn("relative aspect-[2/3] overflow-hidden rounded-lg bg-muted", className)}>
      {failed ? (
        <div className="grid h-full w-full place-items-center text-muted-foreground" role="img" aria-label={alt}>
          <BookOpen className="size-10" strokeWidth={1.2} aria-hidden />
        </div>
      ) : (
        <img
          src={`/api/books/${bookId}/cover?size=${size}`}
          alt={alt}
          loading={eager ? "eager" : "lazy"}
          decoding="async"
          className="h-full w-full object-cover transition-transform duration-300 group-hover:scale-[1.03]"
          onError={() => setFailedFor(bookId)}
        />
      )}
    </div>
  );
}
