import { Link } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";

import { NAV_ITEMS } from "@/lib/nav";

/** The bottom tab bar on small screens: five fixed slots. */
export function MobileNav() {
  const { t } = useTranslation();
  return (
    <nav
      aria-label={t("nav.main")}
      className="fixed inset-x-0 bottom-0 z-30 grid grid-cols-5 border-t bg-background/95 pb-[env(safe-area-inset-bottom)] backdrop-blur md:hidden"
    >
      {NAV_ITEMS.filter((item) => item.mobile).map((item) => (
        <Link
          key={item.to}
          to={item.to}
          activeOptions={{ exact: item.to === "/" }}
          className="flex flex-col items-center gap-0.5 py-2 text-[11px] text-muted-foreground"
          activeProps={{ className: "text-primary-text", "aria-current": "page" }}
        >
          <item.icon className="size-5" aria-hidden />
          {t(`nav.${item.label}`)}
        </Link>
      ))}
    </nav>
  );
}
