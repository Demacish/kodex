import "pdfjs-dist/legacy/web/pdf_viewer.css";

import { ChevronLeft, ChevronRight, List, ZoomIn, ZoomOut } from "lucide-react";
import type { PDFDocumentProxy, PDFPageProxy } from "pdfjs-dist/legacy/build/pdf.mjs";
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import type { Schemas } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Slider } from "@/components/ui/slider";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { cn } from "@/lib/utils";

import { ReaderChrome, SettingRow } from "../ReaderChrome";
import { usePref } from "../prefs";
import type { ProgressUpdate } from "../useProgress";
import { loadPdf } from "./pdfjs";

type Mode = "single" | "scroll";
type Fit = "page" | "width";

interface OutlineItem {
  title: string;
  page: number | null;
  items: OutlineItem[];
}

export interface PdfReaderProps {
  book: Schemas["BookOut"];
  title: string;
  subtitle?: string | null;
  initialPage: number; // 1-based, as v1 stored it
  jump?: { page: number; at: number } | null;
  onProgress: (update: ProgressUpdate) => void;
}

/** Renders one page into a canvas (with its text layer) at ``width`` CSS pixels. */
async function renderPage(page: PDFPageProxy, canvas: HTMLCanvasElement, text: HTMLDivElement | null, width: number, height: number | null) {
  const { TextLayer } = await import("pdfjs-dist/legacy/build/pdf.mjs");
  const unscaled = page.getViewport({ scale: 1 });
  const scale = height ? Math.min(width / unscaled.width, height / unscaled.height) : width / unscaled.width;
  const viewport = page.getViewport({ scale });
  const ratio = window.devicePixelRatio || 1;
  canvas.width = Math.floor(viewport.width * ratio);
  canvas.height = Math.floor(viewport.height * ratio);
  canvas.style.width = `${Math.floor(viewport.width)}px`;
  canvas.style.height = `${Math.floor(viewport.height)}px`;
  const task = page.render({ canvas, viewport, transform: ratio === 1 ? undefined : [ratio, 0, 0, ratio, 0, 0] });
  await task.promise;
  if (text) {
    text.replaceChildren();
    text.style.setProperty("--scale-factor", String(scale));
    text.style.width = `${Math.floor(viewport.width)}px`;
    text.style.height = `${Math.floor(viewport.height)}px`;
    await new TextLayer({ textContentSource: page.streamTextContent(), container: text, viewport }).render();
  }
  return task;
}

export function PdfReader({ book, title, subtitle, initialPage, jump, onProgress }: PdfReaderProps) {
  const { t } = useTranslation();
  const [mode, setMode] = usePref<Mode>("kodex-pdf-mode", "single");
  const [fit, setFit] = usePref<Fit>("kodex-pdf-fit", "page");
  const [doc, setDoc] = useState<PDFDocumentProxy | null>(null);
  const [failed, setFailed] = useState(false);
  const [page, setPage] = useState(Math.max(1, initialPage));
  const [zoom, setZoom] = useState(1);
  const [chrome, setChrome] = useState(true);
  const [outline, setOutline] = useState<OutlineItem[]>([]);
  const [outlineOpen, setOutlineOpen] = useState(false);
  const [size, setSize] = useState({ width: window.innerWidth, height: window.innerHeight });
  const canvas = useRef<HTMLCanvasElement>(null);
  const textLayer = useRef<HTMLDivElement>(null);
  const scroller = useRef<HTMLDivElement>(null);
  const pageRefs = useRef(new Map<number, HTMLDivElement>());
  const total = doc?.numPages ?? 0;

  useEffect(() => {
    let cancelled = false;
    let task: Awaited<ReturnType<typeof loadPdf>> | null = null;
    loadPdf(`/api/books/${book.id}/file`)
      .then((loading) => {
        task = loading;
        return cancelled ? Promise.reject(new Error("closed")) : loading.promise;
      })
      .then(async (pdf) => {
        if (cancelled) return;
        setDoc(pdf);
        setPage((current) => Math.min(current, pdf.numPages));
        const items = (await pdf.getOutline().catch(() => null)) ?? [];
        const resolve = async (nodes: typeof items): Promise<OutlineItem[]> =>
          Promise.all(nodes.map(async (node) => {
            let target: number | null = null;
            try {
              const dest = typeof node.dest === "string" ? await pdf.getDestination(node.dest) : node.dest;
              if (dest?.[0]) target = (await pdf.getPageIndex(dest[0] as never)) + 1;
            } catch {
              target = null;
            }
            return { title: node.title, page: target, items: await resolve(node.items ?? []) };
          }));
        if (!cancelled) setOutline(await resolve(items));
      })
      .catch(() => !cancelled && setFailed(true));
    return () => {
      cancelled = true;
      void task?.destroy();
    };
  }, [book.id]);

  useEffect(() => {
    const listener = () => setSize({ width: window.innerWidth, height: window.innerHeight });
    window.addEventListener("resize", listener);
    return () => window.removeEventListener("resize", listener);
  }, []);

  const report = useCallback(
    (n: number) => total && onProgress({ position: String(n), percent: (n / total) * 100, finished: n >= total }),
    [total, onProgress],
  );
  const go = useCallback(
    (n: number) => {
      if (!total) return;
      const target = Math.max(1, Math.min(total, n));
      setPage(target);
      report(target);
      if (mode === "scroll") pageRefs.current.get(target)?.scrollIntoView({ block: "start" });
    },
    [total, report, mode],
  );
  useEffect(() => {
    if (jump) go(jump.page);
  }, [jump, go]);

  // Single page: draw the current page.
  useEffect(() => {
    if (!doc || mode !== "single" || !canvas.current) return;
    let cancelled = false;
    let task: { cancel: () => void } | null = null;
    void doc.getPage(page).then(async (p) => {
      if (cancelled || !canvas.current) return;
      const width = (fit === "width" ? Math.min(size.width, 1400) : size.width) * zoom;
      task = await renderPage(p, canvas.current, textLayer.current, width, fit === "page" ? size.height * zoom : null).catch(() => null);
    });
    return () => {
      cancelled = true;
      task?.cancel();
    };
  }, [doc, mode, page, size, zoom, fit]);

  // Scrolling: draw pages as they come near, and follow the one in view.
  useEffect(() => {
    if (!doc || mode !== "scroll") return;
    const drawn = new Set<number>();
    const width = Math.min(size.width - 16, 1100) * zoom;
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          const n = Number((entry.target as HTMLElement).dataset.page);
          if (entry.isIntersecting && !drawn.has(n)) {
            drawn.add(n);
            const holder = entry.target as HTMLDivElement;
            void doc.getPage(n).then((p) => renderPage(p, holder.querySelector("canvas")!, holder.querySelector<HTMLDivElement>(".textLayer"), width, null));
          }
        }
        const visible = entries.filter((e) => e.intersectionRatio > 0.5).map((e) => Number((e.target as HTMLElement).dataset.page));
        if (visible.length) {
          const n = Math.min(...visible);
          setPage((current) => {
            if (current !== n) report(n);
            return n;
          });
        }
      },
      { root: scroller.current, rootMargin: "100% 0px", threshold: [0, 0.5, 1] },
    );
    for (const element of pageRefs.current.values()) observer.observe(element);
    return () => observer.disconnect();
  }, [doc, mode, size, zoom, report]);

  useLayoutEffect(() => {
    if (mode === "scroll" && doc) pageRefs.current.get(page)?.scrollIntoView({ block: "start" });
    // eslint-disable-next-line react-hooks/exhaustive-deps -- when the mode or document changes
  }, [mode, doc]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.metaKey || event.ctrlKey || event.altKey) return;
      if ((event.target as HTMLElement | null)?.closest("input, [role=slider], [role=dialog]")) return;
      if (event.key === "m") setChrome((v) => !v);
      else if (event.key === "+" || event.key === "=") setZoom((z) => Math.min(4, z + 0.25));
      else if (event.key === "-") setZoom((z) => Math.max(0.5, z - 0.25));
      else if (mode === "single" && (event.key === "ArrowRight" || event.key === "PageDown" || event.key === " ")) {
        event.preventDefault();
        go(page + 1);
      } else if (mode === "single" && (event.key === "ArrowLeft" || event.key === "PageUp")) {
        event.preventDefault();
        go(page - 1);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [mode, page, go]);

  const onTap = (event: React.MouseEvent) => {
    if ((event.target as HTMLElement).closest("button, a, .textLayer span")) return;
    const x = event.clientX / window.innerWidth;
    if (mode === "single" && x < 0.25) go(page - 1);
    else if (mode === "single" && x > 0.75) go(page + 1);
    else setChrome((v) => !v);
  };

  const label = total ? t("reader.page", { page, total }) : t("common.loading");
  const darkButton = "text-neutral-100 hover:bg-white/10 hover:text-white";

  return (
    <div className="fixed inset-0 bg-neutral-800 text-neutral-100">
      <p className="sr-only" aria-live="polite">{label}</p>
      {failed ? (
        <div className="grid h-full place-items-center text-sm text-neutral-300">{t("reader.loadFailed")}</div>
      ) : mode === "single" ? (
        <div className={cn("absolute inset-0 flex justify-center overflow-auto", fit === "page" && zoom === 1 && "items-center")} onClick={onTap}>
          <div className="relative h-fit w-fit shadow-2xl">
            <canvas ref={canvas} className="block bg-white" />
            <div ref={textLayer} className="textLayer" />
          </div>
        </div>
      ) : (
        <div ref={scroller} className="absolute inset-0 overflow-auto py-16" onClick={onTap}>
          {Array.from({ length: total }, (_, i) => i + 1).map((n) => (
            <div
              key={n}
              data-page={n}
              ref={(element) => {
                if (element) pageRefs.current.set(n, element);
                else pageRefs.current.delete(n);
              }}
              className="relative mx-auto mb-4 w-fit min-h-[50vh] min-w-[50vw] bg-white shadow-xl"
            >
              <canvas className="block" />
              <div className="textLayer" />
            </div>
          ))}
        </div>
      )}

      <Sheet open={outlineOpen} onOpenChange={setOutlineOpen}>
        <SheetContent side="left" className="w-80 overflow-y-auto">
          <SheetHeader>
            <SheetTitle>{t("reader.contents")}</SheetTitle>
          </SheetHeader>
          <Outline items={outline} onPick={(n) => { setOutlineOpen(false); go(n); }} />
        </SheetContent>
      </Sheet>

      <ReaderChrome
        visible={chrome}
        bookId={book.id}
        title={title}
        subtitle={subtitle}
        actions={
          <>
            {outline.length > 0 && (
              <Button variant="ghost" size="icon" className={darkButton} onClick={() => setOutlineOpen(true)} aria-label={t("reader.contents")}>
                <List aria-hidden />
              </Button>
            )}
            <Button variant="ghost" size="icon" className={darkButton} onClick={() => setZoom((z) => Math.max(0.5, z - 0.25))} aria-label={t("reader.zoomOut")}>
              <ZoomOut aria-hidden />
            </Button>
            <Button variant="ghost" size="icon" className={darkButton} onClick={() => setZoom((z) => Math.min(4, z + 0.25))} aria-label={t("reader.zoomIn")}>
              <ZoomIn aria-hidden />
            </Button>
          </>
        }
        settings={
          <>
            <SettingRow label={t("reader.mode")}>
              <ToggleGroup value={[mode]} onValueChange={(value: string[]) => value[0] && setMode(value[0] as Mode)} variant="outline" size="sm">
                <ToggleGroupItem value="single">{t("reader.modes.single")}</ToggleGroupItem>
                <ToggleGroupItem value="scroll">{t("reader.modes.continuous")}</ToggleGroupItem>
              </ToggleGroup>
            </SettingRow>
            {mode === "single" && (
              <SettingRow label={t("reader.fit")}>
                <ToggleGroup value={[fit]} onValueChange={(value: string[]) => value[0] && setFit(value[0] as Fit)} variant="outline" size="sm">
                  <ToggleGroupItem value="page">{t("reader.fits.screen")}</ToggleGroupItem>
                  <ToggleGroupItem value="width">{t("reader.fits.width")}</ToggleGroupItem>
                </ToggleGroup>
              </SettingRow>
            )}
            <SettingRow label={`${t("reader.zoom")} ${Math.round(zoom * 100)} %`}>
              <Slider min={50} max={400} step={25} value={[zoom * 100]} onValueChange={(v) => setZoom((Array.isArray(v) ? v[0]! : (v as number)) / 100)} aria-label={t("reader.zoom")} />
            </SettingRow>
          </>
        }
        bottom={
          <div className="mx-auto flex max-w-3xl items-center gap-3">
            <Button variant="ghost" size="icon" className={darkButton} onClick={() => go(page - 1)} aria-label={t("reader.previous")}>
              <ChevronLeft aria-hidden />
            </Button>
            <Slider className="flex-1" min={1} max={Math.max(1, total)} step={1} value={[page]} onValueChange={(v) => go(Array.isArray(v) ? v[0]! : (v as number))} aria-label={t("reader.goToPage")} aria-valuetext={label} />
            <Button variant="ghost" size="icon" className={darkButton} onClick={() => go(page + 1)} aria-label={t("reader.next")}>
              <ChevronRight aria-hidden />
            </Button>
            <span className="w-24 text-right text-xs tabular-nums text-neutral-300">{label}</span>
          </div>
        }
      />
    </div>
  );
}

function Outline({ items, onPick, depth = 0 }: { items: OutlineItem[]; onPick: (page: number) => void; depth?: number }) {
  return (
    <ul className={cn("space-y-0.5 px-2", depth > 0 && "ml-3 border-l pl-2")}>
      {items.map((item, i) => (
        <li key={`${item.title}-${i}`}>
          <button
            type="button"
            disabled={item.page == null}
            onClick={() => item.page != null && onPick(item.page)}
            className="w-full rounded-md px-2 py-1.5 text-left text-sm hover:bg-muted disabled:opacity-50"
          >
            {item.title}
          </button>
          {item.items.length > 0 && <Outline items={item.items} onPick={onPick} depth={depth + 1} />}
        </li>
      ))}
    </ul>
  );
}
