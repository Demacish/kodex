import { Link } from "@tanstack/react-router";
import { ChevronLeft, ChevronRight, Flag } from "lucide-react";
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type PointerEvent } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { api, type Schemas } from "@/api/client";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Slider } from "@/components/ui/slider";
import { Switch } from "@/components/ui/switch";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { cn } from "@/lib/utils";

import { ReaderChrome, SettingRow } from "../ReaderChrome";
import { usePref } from "../prefs";
import type { ProgressUpdate } from "../useProgress";
import { groupOf, spreads, tapAction, widthStep, type Size } from "./layout";

type Book = Schemas["BookOut"];
export type Mode = "single" | "double" | "continuous" | "webtoon";
type Fit = "screen" | "width";
const MODES: Mode[] = ["single", "double", "continuous", "webtoon"];
const FLAG_REASONS = ["blank", "duplicate", "corrupt", "other"] as const;
const PRELOAD_AHEAD = 3;

interface Filters {
  brightness: number;
  contrast: number;
  saturation: number;
}
const NO_FILTER: Filters = { brightness: 100, contrast: 100, saturation: 100 };

export interface ImageReaderProps {
  book: Book;
  title: string;
  subtitle?: string | null;
  manga: boolean;
  /** Physical page index to open at. */
  initialPage: number;
  /** Set by the parent to move (another device's position); physical index. */
  jump?: { page: number; at: number } | null;
  next?: Book | null;
  onProgress: (update: ProgressUpdate) => void;
}

export function ImageReader({ book, title, subtitle, manga, initialPage, jump, next, onProgress }: ImageReaderProps) {
  const { t } = useTranslation();
  const deleted = useMemo(() => new Set(book.deleted_page_indices ?? []), [book.deleted_page_indices]);
  const pages = useMemo(
    () => Array.from({ length: book.page_count ?? 0 }, (_, i) => i).filter((i) => !deleted.has(i)),
    [book.page_count, deleted],
  );
  const total = pages.length;
  const toLogical = useCallback((physical: number) => {
    const index = pages.findIndex((p) => p >= physical);
    return index === -1 ? Math.max(0, total - 1) : index;
  }, [pages, total]);

  const [mode, setMode] = usePref<Mode>("kodex-reader-mode", "single");
  const [fit, setFit] = usePref<Fit>("kodex-reader-fit", "screen");
  const [rtl, setRtl] = usePref<boolean>(`kodex-reader-rtl-${book.id}`, manga);
  const [coverAlone, setCoverAlone] = usePref<boolean>(`kodex-reader-cover-${book.id}`, true);
  const [trim, setTrim] = usePref<boolean>("kodex-reader-trim", false);
  const [taps, setTaps] = usePref<boolean>("kodex-reader-taps", true);
  const [filters, setFilters] = usePref<Filters>("kodex-reader-filters", NO_FILTER);

  const [page, setPage] = useState(() => toLogical(initialPage));
  const [chrome, setChrome] = useState(true);
  const [ended, setEnded] = useState(false);
  const scroller = useRef<HTMLDivElement>(null);
  const pageRefs = useRef(new Map<number, HTMLElement>());
  const skipScrollSync = useRef(false);

  const dims = api.useQuery("get", "/api/books/{book_id}/pages/dimensions", { params: { path: { book_id: book.id } } }, { staleTime: Infinity });
  const sizes = useMemo<Size[]>(() => {
    const all = (dims.data?.dimensions ?? null) as Size[] | null;
    return pages.map((p) => all?.[p] ?? null);
  }, [dims.data, pages]);
  const groups = useMemo(() => spreads(total, sizes, coverAlone), [total, sizes, coverAlone]);
  const paged = mode === "single" || mode === "double";
  const view = mode === "double" ? groups[groupOf(groups, page)] ?? [page] : [page];

  // Pixels the server should make the page: the screen's, or half for two pages.
  const [viewport, setViewport] = useState(() => window.innerWidth * window.devicePixelRatio);
  useEffect(() => {
    const listener = () => setViewport(window.innerWidth * window.devicePixelRatio);
    window.addEventListener("resize", listener);
    return () => window.removeEventListener("resize", listener);
  }, []);
  const width = widthStep(mode === "double" ? viewport / 2 : mode === "continuous" ? Math.min(viewport, 1000 * window.devicePixelRatio) : viewport);
  const src = useCallback(
    (logical: number) => `/api/books/${book.id}/pages/${pages[logical]}?max_width=${width}${trim ? "&trim=true" : ""}`,
    [book.id, pages, width, trim],
  );

  const report = useCallback(
    (logical: number) => {
      const physical = pages[logical];
      if (physical == null) return;
      const last = mode === "double" ? Math.max(...(groups[groupOf(groups, logical)] ?? [logical])) : logical;
      onProgress({ position: String(physical), percent: ((last + 1) / total) * 100, finished: last >= total - 1 });
    },
    [pages, total, mode, groups, onProgress],
  );

  const go = useCallback(
    (logical: number, { scroll = true } = {}) => {
      const target = Math.max(0, Math.min(total - 1, logical));
      setEnded(false);
      setPage(target);
      report(target);
      if (!paged && scroll) {
        skipScrollSync.current = true;
        pageRefs.current.get(target)?.scrollIntoView({ block: "start" });
        window.setTimeout(() => (skipScrollSync.current = false), 200);
      }
    },
    [total, report, paged],
  );

  const step = useCallback(
    (direction: 1 | -1) => {
      if (mode === "double") {
        const group = groupOf(groups, page) + direction;
        if (group >= groups.length) return setEnded(true);
        if (group >= 0) go(groups[group]![0]!);
        return;
      }
      if (page + direction >= total) return setEnded(true);
      go(page + direction);
    },
    [mode, groups, page, total, go],
  );

  // Another device's position, chosen in the notice.
  useEffect(() => {
    if (jump) go(toLogical(jump.page));
  }, [jump, go, toLogical]);

  // Entering a scrolling mode starts at the current page.
  useLayoutEffect(() => {
    if (!paged) {
      skipScrollSync.current = true;
      pageRefs.current.get(page)?.scrollIntoView({ block: "start" });
      window.setTimeout(() => (skipScrollSync.current = false), 200);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- only when the mode changes
  }, [paged, mode]);

  // Scrolling modes: the page most in view is the current one.
  useEffect(() => {
    if (paged) return;
    const visible = new Map<number, number>();
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) visible.set(Number((entry.target as HTMLElement).dataset.index), entry.intersectionRatio);
        if (skipScrollSync.current) return;
        let best = -1;
        let ratio = 0;
        for (const [index, r] of visible) if (r > ratio) [best, ratio] = [index, r];
        if (best >= 0) {
          setPage((current) => {
            if (current !== best) report(best);
            return best;
          });
        }
      },
      { root: scroller.current, threshold: [0, 0.25, 0.5, 0.75, 1] },
    );
    for (const element of pageRefs.current.values()) observer.observe(element);
    return () => observer.disconnect();
  }, [paged, report, total]);

  // Preload the next pages (and the previous one) in paged modes.
  useEffect(() => {
    if (!paged) return;
    const last = Math.max(...view);
    const wanted = [...Array.from({ length: PRELOAD_AHEAD * (mode === "double" ? 2 : 1) }, (_, i) => last + 1 + i), Math.min(...view) - 1];
    const images = wanted.filter((i) => i >= 0 && i < total).map((i) => {
      const image = new Image();
      image.decoding = "async";
      image.src = src(i);
      return image;
    });
    return () => images.forEach((image) => (image.src = ""));
  }, [paged, view, mode, total, src]);

  // Keyboard: arrows follow the screen, so they swap meaning right to left.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.defaultPrevented || event.metaKey || event.ctrlKey || event.altKey) return;
      const target = event.target as HTMLElement | null;
      if (target?.closest("input, textarea, [role=slider], [role=dialog], [role=menu]")) return;
      const forward = rtl ? "ArrowLeft" : "ArrowRight";
      const back = rtl ? "ArrowRight" : "ArrowLeft";
      if (event.key === "m") return setChrome((v) => !v);
      if (event.key === "Home") return go(0);
      if (event.key === "End") return go(total - 1);
      if (!paged) return;
      if (event.key === forward || event.key === "PageDown" || (event.key === " " && !event.shiftKey)) {
        event.preventDefault();
        step(1);
      } else if (event.key === back || event.key === "PageUp" || (event.key === " " && event.shiftKey)) {
        event.preventDefault();
        step(-1);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [rtl, paged, step, go, total]);

  // Taps and swipes on the page.
  const start = useRef<{ x: number; y: number; at: number } | null>(null);
  const onPointerDown = (event: PointerEvent) => {
    start.current = { x: event.clientX, y: event.clientY, at: Date.now() };
  };
  const onPointerUp = (event: PointerEvent) => {
    const from = start.current;
    start.current = null;
    if (!from || (event.target as HTMLElement).closest("button, a")) return;
    const dx = event.clientX - from.x;
    const dy = event.clientY - from.y;
    if (paged && Math.abs(dx) > 50 && Math.abs(dy) < 60 && Date.now() - from.at < 600) {
      step((dx < 0) !== rtl ? 1 : -1);
      return;
    }
    if (Math.abs(dx) > 10 || Math.abs(dy) > 10) return;
    if (!paged || !taps) return setChrome((v) => !v);
    const action = tapAction(event.clientX / window.innerWidth, rtl);
    if (action === "menu") setChrome((v) => !v);
    else step(action === "next" ? 1 : -1);
  };

  const flag = api.useMutation("post", "/api/books/{book_id}/pages/{page_index}/flag");
  const flagPage = async (reason: (typeof FLAG_REASONS)[number]) => {
    try {
      await flag.mutateAsync({ params: { path: { book_id: book.id, page_index: pages[page] ?? 0 } }, body: { reason } });
      toast.success(t("reader.flagged", { page: page + 1 }));
    } catch {
      toast.error(t("common.errorGeneric"));
    }
  };

  const filter = `brightness(${filters.brightness}%) contrast(${filters.contrast}%) saturate(${filters.saturation}%)`;
  const pageLabel = view.length > 1 ? t("reader.pages", { from: Math.min(...view) + 1, to: Math.max(...view) + 1, total }) : t("reader.page", { page: page + 1, total });

  if (total === 0) {
    return <div className="grid h-dvh place-items-center bg-reader text-sm text-neutral-400">{t("reader.noPages")}</div>;
  }

  return (
    <div className="fixed inset-0 bg-reader text-neutral-100 select-none">
      <p className="sr-only" aria-live="polite">{pageLabel}</p>
      {paged ? (
        <div
          ref={scroller}
          className={cn("absolute inset-0 flex justify-center", fit === "width" ? "items-start overflow-y-auto" : "items-center overflow-hidden", rtl && "flex-row-reverse")}
          style={{ touchAction: "pan-y pinch-zoom" }}
          onPointerDown={onPointerDown}
          onPointerUp={onPointerUp}
        >
          {view.map((logical) => (
            <img
              key={`${logical}-${width}-${trim}`}
              src={src(logical)}
              alt={t("reader.page", { page: logical + 1, total })}
              draggable={false}
              className={cn(
                "block object-contain",
                fit === "width" ? (view.length > 1 ? "h-auto w-1/2" : "h-auto w-full") : view.length > 1 ? "h-full w-1/2" : "h-full w-full",
                view.length > 1 && (logical === Math.min(...view) ? (rtl ? "object-left" : "object-right") : rtl ? "object-right" : "object-left"),
              )}
              style={{ filter }}
            />
          ))}
        </div>
      ) : (
        <div ref={scroller} className="absolute inset-0 overflow-y-auto" onPointerDown={onPointerDown} onPointerUp={onPointerUp}>
          <div className={cn("mx-auto", mode === "continuous" ? "max-w-3xl space-y-3 py-16" : "max-w-2xl")}>
            {pages.map((_, logical) => {
              const size = sizes[logical];
              return (
                <div
                  key={logical}
                  data-index={logical}
                  ref={(element) => {
                    if (element) pageRefs.current.set(logical, element);
                    else pageRefs.current.delete(logical);
                  }}
                  style={{ aspectRatio: size ? `${size[0]} / ${size[1]}` : "2 / 3" }}
                  className="relative w-full bg-neutral-900"
                >
                  <img
                    src={src(logical)}
                    alt={t("reader.page", { page: logical + 1, total })}
                    loading={Math.abs(logical - page) < 3 ? "eager" : "lazy"}
                    decoding="async"
                    draggable={false}
                    className="absolute inset-0 h-full w-full object-contain"
                    style={{ filter }}
                  />
                </div>
              );
            })}
            {next && <NextBook next={next} />}
          </div>
        </div>
      )}

      {ended && paged && (
        <div className="absolute inset-0 z-30 grid place-items-center bg-black/70 p-6 backdrop-blur-sm" onClick={() => setEnded(false)}>
          <div className="space-y-4 text-center" onClick={(event) => event.stopPropagation()}>
            <p className="text-lg font-semibold">{t("reader.finished")}</p>
            {next ? <NextBook next={next} /> : (
              <Button variant="outline" className="border-white/20 bg-transparent text-white hover:bg-white/10" render={<Link to="/books/$bookId" params={{ bookId: book.id }} />}>
                {t("reader.backToBook")}
              </Button>
            )}
          </div>
        </div>
      )}

      <ReaderChrome
        visible={chrome}
        bookId={book.id}
        title={title}
        subtitle={subtitle}
        actions={
          <DropdownMenu>
            <DropdownMenuTrigger render={<Button variant="ghost" size="icon" className="text-neutral-100 hover:bg-white/10 hover:text-white" aria-label={t("reader.flag")} />}>
              <Flag aria-hidden />
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-52">
              <DropdownMenuGroup>
                <DropdownMenuLabel>{t("reader.flagPage", { page: page + 1 })}</DropdownMenuLabel>
                {FLAG_REASONS.map((reason) => (
                  <DropdownMenuItem key={reason} onClick={() => void flagPage(reason)}>{t(`reader.flagReasons.${reason}`)}</DropdownMenuItem>
                ))}
              </DropdownMenuGroup>
            </DropdownMenuContent>
          </DropdownMenu>
        }
        settings={
          <>
            <SettingRow label={t("reader.mode")}>
              <ToggleGroup value={[mode]} onValueChange={(value: string[]) => value[0] && setMode(value[0] as Mode)} variant="outline" size="sm" className="flex-wrap">
                {MODES.map((m) => <ToggleGroupItem key={m} value={m}>{t(`reader.modes.${m}`)}</ToggleGroupItem>)}
              </ToggleGroup>
            </SettingRow>
            {paged && (
              <SettingRow label={t("reader.fit")}>
                <ToggleGroup value={[fit]} onValueChange={(value: string[]) => value[0] && setFit(value[0] as Fit)} variant="outline" size="sm">
                  <ToggleGroupItem value="screen">{t("reader.fits.screen")}</ToggleGroupItem>
                  <ToggleGroupItem value="width">{t("reader.fits.width")}</ToggleGroupItem>
                </ToggleGroup>
              </SettingRow>
            )}
            <SwitchRow label={t("reader.rtl")} checked={rtl} onChange={setRtl} hint={t("reader.rtlHint")} />
            {mode === "double" && <SwitchRow label={t("reader.coverAlone")} checked={coverAlone} onChange={setCoverAlone} hint={t("reader.coverAloneHint")} />}
            <SwitchRow label={t("reader.trim")} checked={trim} onChange={setTrim} hint={t("reader.trimHint")} />
            {paged && <SwitchRow label={t("reader.taps")} checked={taps} onChange={setTaps} hint={t("reader.tapsHint")} />}
            {(["brightness", "contrast", "saturation"] as const).map((key) => (
              <SettingRow key={key} label={`${t(`reader.filters.${key}`)} ${filters[key]} %`}>
                <Slider
                  min={50}
                  max={150}
                  step={5}
                  value={[filters[key]]}
                  onValueChange={(value) => setFilters({ ...filters, [key]: Array.isArray(value) ? value[0] : value })}
                  aria-label={t(`reader.filters.${key}`)}
                />
              </SettingRow>
            ))}
            <Button variant="outline" size="sm" onClick={() => setFilters(NO_FILTER)}>{t("reader.resetFilters")}</Button>
            <p className="text-xs text-muted-foreground">{t("reader.keys")}</p>
          </>
        }
        bottom={
          <div className="mx-auto flex max-w-3xl items-center gap-3">
            <Button variant="ghost" size="icon" className="text-neutral-100 hover:bg-white/10 hover:text-white" onClick={() => (rtl ? step(1) : step(-1))} aria-label={rtl ? t("reader.next") : t("reader.previous")}>
              <ChevronLeft aria-hidden />
            </Button>
            <Slider
              className={cn("flex-1", rtl && "-scale-x-100")}
              min={0}
              max={Math.max(0, total - 1)}
              step={1}
              value={[page]}
              onValueChange={(value) => go(Array.isArray(value) ? value[0]! : (value as number))}
              aria-label={t("reader.goToPage")}
              aria-valuetext={pageLabel}
            />
            <Button variant="ghost" size="icon" className="text-neutral-100 hover:bg-white/10 hover:text-white" onClick={() => (rtl ? step(-1) : step(1))} aria-label={rtl ? t("reader.previous") : t("reader.next")}>
              <ChevronRight aria-hidden />
            </Button>
            <span className="w-24 text-right text-xs tabular-nums text-neutral-300">{pageLabel}</span>
          </div>
        }
      />
    </div>
  );
}

function SwitchRow({ label, checked, onChange, hint }: { label: string; checked: boolean; onChange: (value: boolean) => void; hint?: string }) {
  return (
    <label className="flex items-start justify-between gap-4">
      <span>
        <span className="block text-sm font-medium">{label}</span>
        {hint && <span className="block text-xs text-muted-foreground">{hint}</span>}
      </span>
      <Switch checked={checked} onCheckedChange={onChange} />
    </label>
  );
}

function NextBook({ next }: { next: Book }) {
  const { t } = useTranslation();
  const title = next.book_metadata?.title ?? next.file_path;
  return (
    <Link
      to="/books/$bookId/read"
      params={{ bookId: next.id }}
      className="mx-auto my-10 flex w-fit items-center gap-4 rounded-xl border border-white/10 bg-white/5 p-3 pr-5 text-left text-white transition hover:bg-white/10"
    >
      <img src={`/api/books/${next.id}/cover?size=small`} alt="" className="h-24 w-16 rounded object-cover" />
      <span>
        <span className="block text-xs text-neutral-400">{t("reader.nextInSeries")}</span>
        <span className="block font-medium">{title}</span>
      </span>
      <ChevronRight className="size-5 text-primary-text" aria-hidden />
    </Link>
  );
}
