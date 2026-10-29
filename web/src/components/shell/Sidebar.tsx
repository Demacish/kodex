import { Link, useRouterState } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";

import { useAccount } from "@/lib/account";
import { isCurrent, NAV_ITEMS } from "@/lib/nav";

import { Logo } from "./Logo";

// From lg a sidebar with the names beside the icons; between md and lg (a
// tablet held upright, a phone on its side) a rail with the names below.
const linkClass =
  "aria-[current=page]:bg-sidebar-accent aria-[current=page]:text-primary-text flex flex-col items-center gap-1 rounded-lg px-1 py-2 text-center text-xs leading-tight font-medium text-sidebar-foreground/80 transition-colors hyphens-auto hover:bg-sidebar-accent hover:text-sidebar-accent-foreground lg:flex-row lg:gap-3 lg:px-3 lg:py-2 lg:text-left lg:text-sm";

export function Sidebar() {
  const { t } = useTranslation();
  const account = useAccount();
  const pathname = useRouterState({ select: (state) => state.location.pathname });
  return (
    <aside className="fixed inset-y-0 left-0 z-30 hidden w-24 flex-col border-r border-sidebar-border bg-sidebar md:flex lg:w-60">
      <div className="flex h-14 shrink-0 items-center justify-center px-4 lg:justify-start">
        <Logo compact />
      </div>
      <nav aria-label={t("nav.main")} className="flex-1 space-y-0.5 overflow-y-auto px-2 py-2 lg:px-3">
        {NAV_ITEMS.filter((item) => !item.adminOnly || account.is_admin).map((item) => (
          <Link
            key={item.to}
            to={item.to}
            activeOptions={{ exact: item.to === "/" }}
            className={linkClass}
            aria-current={isCurrent(item, pathname) ? "page" : undefined}
          >
            <item.icon className="size-5 shrink-0 lg:size-4" aria-hidden />
            {t(`nav.${item.label}`)}
          </Link>
        ))}
      </nav>
    </aside>
  );
}
