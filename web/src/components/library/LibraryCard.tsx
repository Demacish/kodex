import { Link } from "@tanstack/react-router";
import { BookOpenText, Images, Library as LibraryIcon } from "lucide-react";
import { useTranslation } from "react-i18next";

import type { Schemas } from "@/api/client";
import { format } from "@/i18n";

const ICONS = { comics: Images, manga: Images, ebooks: BookOpenText } as const;

export function LibraryCard({ library }: { library: Schemas["LibraryOut"] }) {
  const { t } = useTranslation();
  const Icon = ICONS[library.library_type as keyof typeof ICONS] ?? LibraryIcon;
  return (
    <Link
      to="/libraries/$libraryId"
      params={{ libraryId: library.id }}
      className="flex items-center gap-4 rounded-xl border bg-card p-4 transition hover:-translate-y-0.5 hover:border-ring/40 hover:shadow-md"
    >
      <span className="grid size-11 shrink-0 place-items-center rounded-lg bg-accent text-accent-foreground">
        <Icon className="size-5" aria-hidden />
      </span>
      <span className="min-w-0">
        <span className="block truncate font-medium">{library.name}</span>
        <span className="block text-xs text-muted-foreground">
          {t(`library.types.${library.library_type as "comics" | "manga" | "ebooks"}`)}
          {library.last_scanned_at && ` · ${t("library.scanned", { when: format.relative(library.last_scanned_at) })}`}
        </span>
      </span>
    </Link>
  );
}
