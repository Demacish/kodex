import { List, Search } from "lucide-react";
import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import type { Schemas } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Slider } from "@/components/ui/slider";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { useTheme } from "@/lib/theme";
import { cn } from "@/lib/utils";
import type { FoliateLocation, FoliateView, SearchResult, TocItem } from "@/vendor/foliate-js/index";

import { ReaderChrome, SettingRow } from "../ReaderChrome";
import { usePref } from "../prefs";
import type { ProgressUpdate } from "../useProgress";
import { bookStyles, THEMES, type EpubLook } from "./styles";

// A position from another reader, known only as a fraction (readers/positions.ts).
const PERCENT_PREFIX = "percent:";
const FINISHED_AT = 0.995;

const DEFAULT_LOOK: EpubLook = { theme: "auto", font: "publisher", size: 100, lineHeight: 1.5, margin: 48, columns: 2, justify: true, flow: "paginated" };

export interface EpubReaderProps {
  book: Schemas["BookOut"];
  title: string;
  subtitle?: string | null;
  initial: string | null;
  jump?: { position: string; at: number } | null;
  onProgress: (update: ProgressUpdate) => void;
}

async function goToPosition(view: FoliateView, position: string | null) {
  if (position?.startsWith(PERCENT_PREFIX)) {
    const fraction = Number(position.slice(PERCENT_PREFIX.length));
    if (Number.isFinite(fraction)) return view.goToFraction(fraction);
  }
  if (position?.startsWith("epubcfi(")) return view.goTo(position);
  return undefined;
}

export function EpubReader({ book, title, subtitle, initial, jump, onProgress }: EpubReaderProps) {
  const { t } = useTranslation();
  const { resolved } = useTheme();
  const [look, setLook] = usePref<EpubLook>("kodex-epub-look", DEFAULT_LOOK);
  const host = useRef<HTMLDivElement>(null);
  const viewRef = useRef<FoliateView | null>(null);
  const [state, setState] = useState<"loading" | "ready" | "error">("loading");
  const [location, setLocation] = useState<FoliateLocation | null>(null);
  const [toc, setToc] = useState<TocItem[]>([]);
  const [panel, setPanel] = useState<"toc" | "search" | null>(null);
  const [chrome, setChrome] = useState(true);
  const report = useRef(onProgress);
  report.current = onProgress;
  const toggleChrome = useRef(() => setChrome((v) => !v));

  useEffect(() => {
    let cancelled = false;
    let view: FoliateView | null = null;
    (async () => {
      try {
        await import("@/vendor/foliate-js/view.js");
        const response = await fetch(`/api/books/${book.id}/file`, { credentials: "same-origin" });
        if (!response.ok) throw new Error(String(response.status));
        const file = new File([await response.blob()], `${book.id}.epub`, { type: "application/epub+zip" });
        if (cancelled || !host.current) return;
        view = document.createElement("foliate-view") as FoliateView;
        view.className = "block h-full w-full";
        host.current.append(view);
        viewRef.current = view;
        view.addEventListener("relocate", (event) => {
          const detail = (event as CustomEvent<FoliateLocation>).detail;
          setLocation(detail);
          if (detail.cfi) {
            report.current({ position: detail.cfi, percent: detail.fraction * 100, finished: detail.fraction >= FINISHED_AT, chapter: detail.tocItem?.label?.trim() || null });
          }
        });
        view.addEventListener("load", (event) => {
          const { doc } = (event as CustomEvent<{ doc: Document }>).detail;
          doc.addEventListener("keydown", (e) => window.dispatchEvent(new KeyboardEvent("keydown", { key: e.key, shiftKey: e.shiftKey })));
          doc.addEventListener("click", (e) => {
            if ((e.target as Element | null)?.closest("a")) return;
            if (doc.getSelection()?.toString()) return;
            const width = doc.defaultView?.innerWidth ?? window.innerWidth;
            const x = (e as MouseEvent).clientX % width / width;
            if (x < 0.25) void view?.goLeft();
            else if (x > 0.75) void view?.goRight();
            else toggleChrome.current();
          });
        });
        await view.open(file);
        if (cancelled) return;
        setToc(view.book.toc ?? []);
        await view.init({ lastLocation: initial?.startsWith("epubcfi(") ? initial : null, showTextStart: !initial });
        if (initial?.startsWith(PERCENT_PREFIX)) await goToPosition(view, initial);
        setState("ready");
      } catch {
        if (!cancelled) setState("error");
      }
    })();
    return () => {
      cancelled = true;
      view?.close();
      view?.remove();
      viewRef.current = null;
    };
    // The book opens once; later positions come through `jump`.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [book.id]);

  // The look: the book's styles, the theme, the layout.
  useEffect(() => {
    const view = viewRef.current;
    if (!view || state !== "ready") return;
    const theme = look.theme === "auto" ? (resolved === "dark" ? "dark" : "light") : look.theme;
    view.renderer.setStyles(bookStyles(look, THEMES[theme]));
    view.renderer.setAttribute("flow", look.flow);
    view.renderer.setAttribute("gap", "6%");
    view.renderer.setAttribute("margin", `${look.margin}px`);
    view.renderer.setAttribute("max-inline-size", "760px");
    view.renderer.setAttribute("max-column-count", String(look.columns));
    if (host.current) host.current.style.background = THEMES[theme].background;
  }, [look, resolved, state]);

  useEffect(() => {
    const view = viewRef.current;
    if (jump && view) void goToPosition(view, jump.position);
  }, [jump]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const view = viewRef.current;
      if (!view || (event.target as HTMLElement | null)?.closest?.("input, [role=slider], [role=dialog]")) return;
      if (event.key === "ArrowLeft" || event.key === "PageUp") void view.goLeft();
      else if (event.key === "ArrowRight" || event.key === "PageDown" || event.key === " ") void view.goRight();
      else if (event.key === "m") setChrome((v) => !v);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const goTo = useCallback((target: string) => {
    setPanel(null);
    void viewRef.current?.goTo(target);
  }, []);

  const percent = Math.round((location?.fraction ?? 0) * 100);
  const where = location?.tocItem?.label?.trim();
  const darkButton = "text-neutral-100 hover:bg-white/10 hover:text-white";

  return (
    <div className="fixed inset-0 bg-reader text-neutral-100">
      <div ref={host} className={cn("absolute inset-0 pt-6 pb-8 transition-opacity", state === "ready" ? "opacity-100" : "opacity-0")} />
      {state !== "ready" && (
        <div className="absolute inset-0 grid place-items-center text-sm text-neutral-400">
          {state === "error" ? t("reader.loadFailed") : t("common.loading")}
        </div>
      )}
      <p className="sr-only" aria-live="polite">{where ? `${where}, ${percent} %` : `${percent} %`}</p>

      <Sheet open={panel !== null} onOpenChange={(open) => !open && setPanel(null)}>
        <SheetContent side="left" className="w-80 overflow-y-auto">
          <SheetHeader>
            <SheetTitle>{panel === "search" ? t("reader.searchBook") : t("reader.contents")}</SheetTitle>
          </SheetHeader>
          {panel === "toc" ? <Toc items={toc} current={location?.tocItem?.href} onPick={goTo} /> : <BookSearch view={viewRef.current} onPick={goTo} />}
        </SheetContent>
      </Sheet>

      <ReaderChrome
        visible={chrome}
        bookId={book.id}
        title={title}
        subtitle={where ?? subtitle}
        actions={
          <>
            <Button variant="ghost" size="icon" className={darkButton} onClick={() => setPanel("search")} aria-label={t("reader.searchBook")}>
              <Search aria-hidden />
            </Button>
            {toc.length > 0 && (
              <Button variant="ghost" size="icon" className={darkButton} onClick={() => setPanel("toc")} aria-label={t("reader.contents")}>
                <List aria-hidden />
              </Button>
            )}
          </>
        }
        settings={
          <>
            <SettingRow label={t("reader.epub.theme")}>
              <ToggleGroup value={[look.theme]} onValueChange={(v: string[]) => v[0] && setLook({ ...look, theme: v[0] as EpubLook["theme"] })} variant="outline" size="sm" className="flex-wrap">
                {(["auto", "light", "sepia", "dark"] as const).map((theme) => <ToggleGroupItem key={theme} value={theme}>{t(`reader.epub.themes.${theme}`)}</ToggleGroupItem>)}
              </ToggleGroup>
            </SettingRow>
            <SettingRow label={t("reader.epub.font")}>
              <ToggleGroup value={[look.font]} onValueChange={(v: string[]) => v[0] && setLook({ ...look, font: v[0] as EpubLook["font"] })} variant="outline" size="sm">
                {(["publisher", "serif", "sans"] as const).map((font) => <ToggleGroupItem key={font} value={font}>{t(`reader.epub.fonts.${font}`)}</ToggleGroupItem>)}
              </ToggleGroup>
            </SettingRow>
            <SettingRow label={`${t("reader.epub.size")} ${look.size} %`}>
              <Slider min={70} max={200} step={5} value={[look.size]} onValueChange={(v) => setLook({ ...look, size: Array.isArray(v) ? v[0]! : (v as number) })} aria-label={t("reader.epub.size")} />
            </SettingRow>
            <SettingRow label={`${t("reader.epub.lineHeight")} ${look.lineHeight.toFixed(1)}`}>
              <Slider min={1} max={2.2} step={0.1} value={[look.lineHeight]} onValueChange={(v) => setLook({ ...look, lineHeight: Array.isArray(v) ? v[0]! : (v as number) })} aria-label={t("reader.epub.lineHeight")} />
            </SettingRow>
            <SettingRow label={`${t("reader.epub.margin")} ${look.margin} px`}>
              <Slider min={0} max={120} step={8} value={[look.margin]} onValueChange={(v) => setLook({ ...look, margin: Array.isArray(v) ? v[0]! : (v as number) })} aria-label={t("reader.epub.margin")} />
            </SettingRow>
            <SettingRow label={t("reader.epub.layout")}>
              <ToggleGroup value={[look.flow]} onValueChange={(v: string[]) => v[0] && setLook({ ...look, flow: v[0] as EpubLook["flow"] })} variant="outline" size="sm">
                <ToggleGroupItem value="paginated">{t("reader.epub.paginated")}</ToggleGroupItem>
                <ToggleGroupItem value="scrolled">{t("reader.epub.scrolled")}</ToggleGroupItem>
              </ToggleGroup>
            </SettingRow>
            {look.flow === "paginated" && (
              <SettingRow label={t("reader.epub.columns")}>
                <ToggleGroup value={[String(look.columns)]} onValueChange={(v: string[]) => v[0] && setLook({ ...look, columns: Number(v[0]) })} variant="outline" size="sm">
                  <ToggleGroupItem value="1">1</ToggleGroupItem>
                  <ToggleGroupItem value="2">2</ToggleGroupItem>
                </ToggleGroup>
              </SettingRow>
            )}
            <label className="flex items-center justify-between gap-4 text-sm font-medium">
              {t("reader.epub.justify")}
              <input type="checkbox" className="size-4 accent-primary" checked={look.justify} onChange={(e) => setLook({ ...look, justify: e.target.checked })} />
            </label>
            <Button variant="outline" size="sm" onClick={() => setLook(DEFAULT_LOOK)}>{t("reader.resetFilters")}</Button>
          </>
        }
        bottom={
          <div className="mx-auto flex max-w-3xl items-center gap-3">
            <Slider
              className="flex-1"
              min={0}
              max={1000}
              step={1}
              value={[Math.round((location?.fraction ?? 0) * 1000)]}
              onValueCommitted={(v) => void viewRef.current?.goToFraction((Array.isArray(v) ? v[0]! : (v as number)) / 1000)}
              aria-label={t("reader.goToPosition")}
              aria-valuetext={`${percent} %`}
            />
            <span className="w-28 text-right text-xs tabular-nums text-neutral-300">
              {location?.location ? t("reader.location", { current: location.location.current + 1, total: location.location.total }) : `${percent} %`}
            </span>
          </div>
        }
      />
    </div>
  );
}

function Toc({ items, current, onPick, depth = 0 }: { items: TocItem[]; current?: string; onPick: (href: string) => void; depth?: number }) {
  return (
    <ul className={cn("space-y-0.5 px-2", depth > 0 && "ml-3 border-l pl-2")}>
      {items.map((item, i) => (
        <li key={`${item.href}-${i}`}>
          <button
            type="button"
            onClick={() => onPick(item.href)}
            aria-current={item.href === current ? "true" : undefined}
            className="w-full rounded-md px-2 py-1.5 text-left text-sm hover:bg-muted aria-[current]:font-semibold aria-[current]:text-primary-text"
          >
            {item.label?.trim()}
          </button>
          {item.subitems && item.subitems.length > 0 && <Toc items={item.subitems} current={current} onPick={onPick} depth={depth + 1} />}
        </li>
      ))}
    </ul>
  );
}

function BookSearch({ view, onPick }: { view: FoliateView | null; onPick: (cfi: string) => void }) {
  const { t } = useTranslation();
  const [results, setResults] = useState<{ cfi: string; excerpt: { pre: string; match: string; post: string }; label?: string }[]>([]);
  const [busy, setBusy] = useState(false);
  const run = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const query = String(new FormData(event.currentTarget).get("q") ?? "").trim();
    if (!view || !query) return;
    setBusy(true);
    setResults([]);
    const found: typeof results = [];
    for await (const result of view.search({ query })) {
      if (result === "done") break;
      const r = result as SearchResult;
      for (const item of r.subitems ?? []) found.push({ ...item, label: r.label });
      if (found.length >= 200) break;
      setResults([...found]);
    }
    setBusy(false);
  };
  return (
    <div className="space-y-3 px-4 pb-6">
      <form role="search" onSubmit={run} className="flex gap-2">
        <Input name="q" placeholder={t("reader.searchBook")} aria-label={t("reader.searchBook")} autoFocus />
        <Button type="submit" disabled={busy}>{t("common.search")}</Button>
      </form>
      {!busy && results.length === 0 && <p className="text-sm text-muted-foreground">{t("reader.searchHint")}</p>}
      <ul className="space-y-1">
        {results.map((result) => (
          <li key={result.cfi}>
            <button type="button" onClick={() => onPick(result.cfi)} className="w-full rounded-md px-2 py-1.5 text-left text-sm hover:bg-muted">
              {result.label && <span className="block text-xs text-muted-foreground">{result.label}</span>}
              {result.excerpt.pre}<mark className="bg-primary/30 text-foreground">{result.excerpt.match}</mark>{result.excerpt.post}
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
