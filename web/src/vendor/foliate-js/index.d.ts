/** The parts of foliate-js (plain JavaScript) that Kodex uses. */
export interface TocItem {
  label: string;
  href: string;
  subitems?: TocItem[];
}

export interface FoliateLocation {
  fraction: number;
  cfi: string;
  tocItem?: { label?: string; href?: string } | null;
  pageItem?: { label?: string } | null;
  location?: { current: number; next: number; total: number };
  section?: { current: number; total: number };
}

export interface SearchResult {
  cfi?: string;
  excerpt?: { pre: string; match: string; post: string };
  label?: string;
  subitems?: { cfi: string; excerpt: { pre: string; match: string; post: string } }[];
}

export interface FoliateRenderer extends HTMLElement {
  setStyles(styles: string | [string, string]): void;
  next(): Promise<void>;
  prev(): Promise<void>;
}

export interface FoliateView extends HTMLElement {
  book: { toc?: TocItem[]; metadata?: { title?: unknown; language?: string }; dir?: string; rendition?: { layout?: string } };
  renderer: FoliateRenderer;
  lastLocation: FoliateLocation | null;
  open(book: Blob | File | string): Promise<void>;
  init(options: { lastLocation?: string | null; showTextStart?: boolean }): Promise<void>;
  close(): void;
  goTo(target: string | number): Promise<void>;
  goToFraction(fraction: number): Promise<void>;
  next(distance?: number): Promise<void>;
  prev(distance?: number): Promise<void>;
  goLeft(): Promise<void>;
  goRight(): Promise<void>;
  search(options: { query: string; matchCase?: boolean; matchWholeWords?: boolean }): AsyncGenerator<SearchResult | "done">;
  clearSearch(): void;
}
