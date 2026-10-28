import { Link } from "@tanstack/react-router";
import { ChevronRight } from "lucide-react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

/** A titled row of covers that scrolls sideways on small screens. */
export function Shelf({ title, to, search, children }: {
  title: string;
  to?: string;
  search?: Record<string, unknown>;
  children: ReactNode;
}) {
  const { t } = useTranslation();
  return (
    <section className="mb-10" aria-label={title}>
      <div className="mb-3 flex items-baseline justify-between gap-3">
        <h2 className="text-lg font-semibold tracking-tight">{title}</h2>
        {to && (
          <Link to={to} search={search} className="flex items-center text-sm text-muted-foreground hover:text-foreground">
            {t("common.showAll")}
            <ChevronRight className="size-4" aria-hidden />
          </Link>
        )}
      </div>
      <ul className="-mx-4 flex snap-x gap-4 overflow-x-auto px-4 pb-2 [scrollbar-width:thin] md:mx-0 md:grid md:grid-cols-4 md:overflow-visible md:px-0 lg:grid-cols-6">
        {children}
      </ul>
    </section>
  );
}

export function ShelfItem({ children }: { children: ReactNode }) {
  return <li className="w-32 shrink-0 snap-start sm:w-36 md:w-auto">{children}</li>;
}
