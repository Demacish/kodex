import { Link } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";

import { useAccount } from "@/lib/account";
import { NAV_ITEMS } from "@/lib/nav";

import { Logo } from "./Logo";

const linkClass =
  "flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium text-sidebar-foreground/80 transition-colors hover:bg-sidebar-accent hover:text-sidebar-accent-foreground";

export function Sidebar() {
  const { t } = useTranslation();
  const account = useAccount();
  return (
    <aside className="fixed inset-y-0 left-0 z-30 hidden w-60 flex-col border-r border-sidebar-border bg-sidebar md:flex">
      <div className="flex h-14 items-center px-4">
        <Logo />
      </div>
      <nav aria-label={t("nav.main")} className="flex-1 space-y-0.5 overflow-y-auto px-3 py-2">
        {NAV_ITEMS.filter((item) => !item.adminOnly || account.is_admin).map((item) => (
          <Link
            key={item.to}
            to={item.to}
            activeOptions={{ exact: item.to === "/" }}
            className={linkClass}
            activeProps={{ className: "bg-sidebar-accent text-primary-text", "aria-current": "page" }}
          >
            <item.icon className="size-4 shrink-0" aria-hidden />
            {t(`nav.${item.label}`)}
          </Link>
        ))}
      </nav>
    </aside>
  );
}
