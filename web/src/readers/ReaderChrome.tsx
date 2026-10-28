import { Link } from "@tanstack/react-router";
import { ChevronLeft, Maximize, Minimize, Settings2 } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { cn } from "@/lib/utils";

export function useFullscreen() {
  const [on, setOn] = useState(() => !!document.fullscreenElement);
  useEffect(() => {
    const listener = () => setOn(!!document.fullscreenElement);
    document.addEventListener("fullscreenchange", listener);
    return () => document.removeEventListener("fullscreenchange", listener);
  }, []);
  const toggle = () => {
    if (document.fullscreenElement) void document.exitFullscreen();
    else void document.documentElement.requestFullscreen?.().catch(() => undefined);
  };
  return { on, toggle, supported: !!document.documentElement.requestFullscreen };
}

/** The bars over every reader: back, title, actions above; whatever the reader puts below. */
export function ReaderChrome({ visible, bookId, title, subtitle, actions, settings, settingsTitle, bottom }: {
  visible: boolean;
  bookId: number;
  title: string;
  subtitle?: string | null;
  actions?: ReactNode;
  settings?: ReactNode;
  settingsTitle?: string;
  bottom?: ReactNode;
}) {
  const { t } = useTranslation();
  const fullscreen = useFullscreen();
  const [settingsOpen, setSettingsOpen] = useState(false);
  const bar = "pointer-events-auto bg-neutral-950/85 text-neutral-100 backdrop-blur transition-all duration-200";
  return (
    <>
      <header
        className={cn(bar, "fixed inset-x-0 top-0 z-40 flex h-14 items-center gap-2 px-2 pt-[env(safe-area-inset-top)] sm:px-4", !visible && "pointer-events-none -translate-y-full opacity-0")}
        aria-hidden={!visible}
      >
        <Button
          variant="ghost"
          size="icon"
          className="text-neutral-100 hover:bg-white/10 hover:text-white"
          render={<Link to="/books/$bookId" params={{ bookId }} aria-label={t("reader.close")} />}
        >
          <ChevronLeft aria-hidden />
        </Button>
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm font-medium">{title}</div>
          {subtitle && <div className="truncate text-xs text-neutral-400">{subtitle}</div>}
        </div>
        {actions}
        {settings && (
          <Button variant="ghost" size="icon" className="text-neutral-100 hover:bg-white/10 hover:text-white" onClick={() => setSettingsOpen(true)} aria-label={t("reader.settings")}>
            <Settings2 aria-hidden />
          </Button>
        )}
        {fullscreen.supported && (
          <Button variant="ghost" size="icon" className="text-neutral-100 hover:bg-white/10 hover:text-white" onClick={fullscreen.toggle} aria-label={fullscreen.on ? t("reader.exitFullscreen") : t("reader.fullscreen")}>
            {fullscreen.on ? <Minimize aria-hidden /> : <Maximize aria-hidden />}
          </Button>
        )}
      </header>
      {bottom && (
        <footer
          className={cn(bar, "fixed inset-x-0 bottom-0 z-40 px-4 pt-3 pb-[max(0.75rem,env(safe-area-inset-bottom))]", !visible && "pointer-events-none translate-y-full opacity-0")}
          aria-hidden={!visible}
        >
          {bottom}
        </footer>
      )}
      {settings && (
        <Sheet open={settingsOpen} onOpenChange={setSettingsOpen}>
          <SheetContent side="right" className="w-80 overflow-y-auto">
            <SheetHeader>
              <SheetTitle>{settingsTitle ?? t("reader.settings")}</SheetTitle>
            </SheetHeader>
            <div className="space-y-6 px-4 pb-6">{settings}</div>
          </SheetContent>
        </Sheet>
      )}
    </>
  );
}

export function SettingRow({ label, children, hint }: { label: string; children: ReactNode; hint?: string }) {
  return (
    <div className="space-y-2">
      <div className="text-sm font-medium">{label}</div>
      {children}
      {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
    </div>
  );
}
