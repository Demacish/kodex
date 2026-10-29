import { Link } from "@tanstack/react-router";
import { ChevronRight } from "lucide-react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

/** A titled row of covers that scrolls sideways, until the screen is wide enough for a grid (lg). */
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
          <Link to={to} search={search} className="-my-2 flex items-center py-2 text-sm text-muted-foreground hover:text-foreground">
            {t("common.showAll")}
            <ChevronRight className="size-4" aria-hidden />
          </Link>
        )}
      </div>
      <ul className="-mx-4 flex snap-x scroll-px-4 gap-3 overflow-x-auto px-4 pb-2 [scrollbar-width:thin] sm:gap-4 md:-mx-6 md:scroll-px-6 md:px-6 lg:mx-0 lg:grid lg:grid-cols-6 lg:overflow-visible lg:px-0">
        {children}
      </ul>
    </section>
  );
}

export function ShelfItem({ children }: { children: ReactNode }) {
  return <li className="w-28 shrink-0 snap-start sm:w-36 lg:w-auto">{children}</li>;
}
