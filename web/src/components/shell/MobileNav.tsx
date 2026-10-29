import { Link, useRouterState } from "@tanstack/react-router";
import { Ellipsis } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetTrigger } from "@/components/ui/sheet";
import { useAccount } from "@/lib/account";
import { isCurrent, NAV_ITEMS } from "@/lib/nav";
import { cn } from "@/lib/utils";

const tab = "group flex flex-col items-center gap-1 pt-2 pb-1.5 text-xs font-medium text-muted-foreground outline-none aria-[current=page]:text-foreground";
const pill =
  "grid h-8 w-14 place-items-center rounded-full transition-colors group-focus-visible:ring-2 group-focus-visible:ring-ring group-aria-[current=page]:bg-primary/15 group-aria-[current=page]:text-primary-text";

/** The bottom tab bar on phones: the tabs marked `mobile`, and Mer, a sheet with the rest. */
export function MobileNav() {
  const { t } = useTranslation();
  const account = useAccount();
  const [open, setOpen] = useState(false);
  const pathname = useRouterState({ select: (state) => state.location.pathname });
  const rest = NAV_ITEMS.filter((item) => !item.mobile && (!item.adminOnly || account.is_admin));
  const elsewhere = rest.some((item) => isCurrent(item, pathname));
  return (
    <nav
      aria-label={t("nav.main")}
      className="fixed inset-x-0 bottom-0 z-30 grid grid-cols-5 border-t bg-background/95 pb-[env(safe-area-inset-bottom)] backdrop-blur md:hidden"
    >
      {NAV_ITEMS.filter((item) => item.mobile).map((item) => (
        // The router marks a link to "/" current on every page unless exact; isCurrent adds a link's own pages.
        <Link key={item.to} to={item.to} activeOptions={{ exact: item.to === "/" }} className={tab} aria-current={isCurrent(item, pathname) ? "page" : undefined}>
          <span className={pill}>
            <item.icon className="size-5" aria-hidden />
          </span>
          {t(`nav.${item.label}`)}
        </Link>
      ))}
      <Sheet open={open} onOpenChange={setOpen}>
        <SheetTrigger className={tab} aria-current={elsewhere ? "page" : undefined}>
          <span className={pill}>
            <Ellipsis className="size-5" aria-hidden />
          </span>
          {t("common.more")}
        </SheetTrigger>
        <SheetContent side="bottom" className="max-h-[85dvh] rounded-t-2xl pb-[calc(1rem+env(safe-area-inset-bottom))]">
          <SheetHeader>
            <SheetTitle>{t("common.more")}</SheetTitle>
          </SheetHeader>
          <ul className="grid grid-cols-3 gap-2 overflow-y-auto px-4">
            {rest.map((item) => (
              <li key={item.to}>
                <Link
                  to={item.to}
                  onClick={() => setOpen(false)}
                  className={cn(
                    "flex h-20 flex-col items-center justify-center gap-1.5 rounded-xl bg-muted/50 px-1 text-center text-sm leading-tight font-medium hyphens-auto transition-colors hover:bg-muted",
                    "aria-[current=page]:bg-primary/15 aria-[current=page]:text-primary-text",
                  )}
                  aria-current={isCurrent(item, pathname) ? "page" : undefined}
                >
                  <item.icon className="size-5" aria-hidden />
                  {t(`nav.${item.label}`)}
                </Link>
              </li>
            ))}
          </ul>
        </SheetContent>
      </Sheet>
    </nav>
  );
}
