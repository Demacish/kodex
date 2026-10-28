/**
 * Stored positions as the place each reader opens at (backend:
 * kodex/reading/positions.py). A position keeps the kind of locator the
 * reader that made it uses; a reader that gets another kind (KOReader's
 * XPointer in the EPUB reader, say) opens at the progression instead.
 */
import type { Schemas } from "@/api/client";

export type ReaderKind = "image" | "pdf" | "epub";
type Stored = Pick<Schemas["ReadingProgressOut"], "position" | "locator_kind" | "progress_percent">;

const PAGE_BASED = ["cbz", "cbr", "cb7", "image_folder"];

export function readerKind(format: string): ReaderKind | null {
  if (PAGE_BASED.includes(format)) return "image";
  if (format === "pdf") return "pdf";
  return format === "epub" ? "epub" : null;
}

/** The kind of locator each reader saves. */
export const LOCATOR = { image: "page", pdf: "pdf", epub: "cfi" } as const satisfies Record<ReaderKind, string>;

function number(value: string | null | undefined): number | null {
  return value != null && /^\d+$/.test(value) ? Number(value) : null;
}

/** 0-based page for the image reader, 1-based for the PDF reader, a CFI or `percent:` fraction for EPUB. */
export function openAt(reader: ReaderKind, stored: Stored | null | undefined, pageCount: number | null | undefined): string | null {
  if (!stored) return null;
  const fraction = Math.max(0, Math.min(1, stored.progress_percent / 100));
  const value = number(stored.position);
  if (reader === "epub") {
    if (stored.locator_kind === "cfi" && stored.position) return stored.position;
    return fraction > 0 ? `percent:${fraction}` : null;
  }
  let index: number | null = null;
  if (value != null && stored.locator_kind === "page") index = value;
  else if (value != null && stored.locator_kind === "pdf") index = Math.max(value - 1, 0);
  else if (pageCount) index = Math.min(Math.floor(fraction * pageCount), pageCount - 1);
  if (index == null) return null;
  return String(reader === "pdf" ? index + 1 : index);
}
