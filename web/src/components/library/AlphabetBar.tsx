import { useTranslation } from "react-i18next";

import { api } from "@/api/client";
import { cn } from "@/lib/utils";

/** Jumps to where a letter starts in a title-sorted series list. */
export function AlphabetBar({ libraryId, following, limit, offset, onJump }: {
  libraryId?: number;
  following?: boolean;
  limit: number;
  offset: number;
  onJump: (offset: number) => void;
}) {
  const { t } = useTranslation();
  const letters = api.useQuery("get", "/api/series/letters", {
    params: { query: { library_id: libraryId, following } },
  });
  if (!letters.data || letters.data.length < 2) return null;
  const page = Math.floor(offset / limit);
  return (
    <nav aria-label={t("list.jumpToLetter")} className="-mx-4 mb-4 flex gap-1 overflow-x-auto px-4 [scrollbar-width:none] sm:mx-0 sm:flex-wrap sm:px-0">
      {letters.data.map((entry) => {
        const target = Math.floor(entry.offset / limit) * limit;
        const current = Math.floor(entry.offset / limit) === page;
        return (
          <button
            key={entry.letter}
            type="button"
            onClick={() => onJump(target)}
            aria-current={current ? "true" : undefined}
            title={t("list.letterCount", { count: entry.count })}
            className={cn(
              "min-w-7 shrink-0 rounded-md px-1.5 py-0.5 text-xs font-medium transition pointer-coarse:h-9 pointer-coarse:min-w-9 pointer-coarse:text-sm",
              current ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:bg-muted hover:text-foreground",
            )}
          >
            {entry.letter}
          </button>
        );
      })}
    </nav>
  );
}
