import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { CommandPalette } from "./CommandPalette";
import { MobileNav } from "./MobileNav";
import { Sidebar } from "./Sidebar";
import { TopBar } from "./TopBar";

export function AppShell({ children }: { children: ReactNode }) {
  const { t } = useTranslation();
  return (
    <div className="min-h-dvh">
      <a href="#main" className="sr-only z-50 rounded-md bg-primary px-3 py-2 text-primary-foreground focus:not-sr-only focus:fixed focus:top-2 focus:left-2">
        {t("app.skipToContent")}
      </a>
      <Sidebar />
      <div className="md:pl-60">
        <TopBar />
        <main id="main" tabIndex={-1} className="mx-auto max-w-7xl px-4 py-6 pb-24 outline-none md:px-6 md:pb-10">
          {children}
        </main>
      </div>
      <MobileNav />
      <CommandPalette />
    </div>
  );
}
