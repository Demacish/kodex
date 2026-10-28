import { useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { Play, X } from "lucide-react";
import { useTranslation } from "react-i18next";

import { api, type Schemas } from "@/api/client";
import { Progress } from "@/components/ui/progress";

import { Cover } from "./Cover";

type Item = Schemas["ContinueReadingItem"];

export function ContinueCard({ item }: { item: Item }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const dismiss = api.useMutation("post", "/api/books/{book_id}/progress/dismiss", {
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["get", "/api/me/continue-reading"] }),
  });
  const details = [
    item.number != null ? t(item.edition_type === "collected" ? "book.volume" : "book.issue", { number: String(item.number) }) : null,
    item.chapter ?? (item.pages_left != null ? t("book.pagesLeft", { count: item.pages_left }) : null),
  ].filter(Boolean);
  return (
    <div className="group relative">
      <Link to="/books/$bookId/read" params={{ bookId: item.book_id }} className="block rounded-lg">
        <div className="relative transition-transform duration-200 group-hover:-translate-y-0.5">
          <Cover bookId={item.book_id} alt="" className="shadow-sm ring-1 ring-foreground/5" />
          <span className="absolute inset-0 grid place-items-center rounded-lg bg-black/0 transition group-hover:bg-black/30">
            <Play className="size-8 fill-white text-white opacity-0 drop-shadow transition group-hover:opacity-100" strokeWidth={0} aria-hidden />
          </span>
          <Progress value={item.progress_percent} className="absolute inset-x-2 bottom-2 h-1" aria-hidden />
        </div>
        <div className="mt-2 line-clamp-2 text-sm leading-snug font-medium">{item.title}</div>
        {details.length > 0 && <div className="text-xs text-muted-foreground">{details.join(" · ")}</div>}
      </Link>
      <button
        type="button"
        onClick={() => dismiss.mutate({ params: { path: { book_id: item.book_id } } })}
        aria-label={t("home.dismiss", { title: item.title })}
        title={t("home.dismissShort")}
        className="absolute top-1.5 right-1.5 grid size-6 place-items-center rounded-full bg-black/60 text-white opacity-0 transition group-focus-within:opacity-100 group-hover:opacity-100 hover:bg-black/80 focus-visible:opacity-100"
      >
        <X className="size-3.5" aria-hidden />
      </button>
    </div>
  );
}
