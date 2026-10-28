/** Pure layout rules of the image reader, kept apart so they can be tested. */

export type Size = [number, number] | null | undefined;

/** The server re-encodes pages at these widths (backend: kodex/reading/pages.py). */
export const WIDTH_STEPS = [480, 720, 1080, 1440, 1920, 2560, 3840];

export function widthStep(pixels: number): number {
  return WIDTH_STEPS.find((step) => step >= pixels) ?? WIDTH_STEPS[WIDTH_STEPS.length - 1]!;
}

export function isWide(size: Size): boolean {
  return !!size && size[0] > size[1] * 1.1;
}

/**
 * Two-page spreads: pages in pairs, a wide page (already a spread) alone,
 * and with ``coverAlone`` the first page alone so the pairs line up the way
 * the printed book does. Indices are into the page list.
 */
export function spreads(count: number, sizes: Size[], coverAlone: boolean): number[][] {
  const groups: number[][] = [];
  let i = 0;
  if (coverAlone && count > 0) {
    groups.push([0]);
    i = 1;
  }
  while (i < count) {
    if (isWide(sizes[i]) || i + 1 >= count || isWide(sizes[i + 1])) {
      groups.push([i]);
      i += 1;
    } else {
      groups.push([i, i + 1]);
      i += 2;
    }
  }
  return groups;
}

export function groupOf(groups: number[][], page: number): number {
  const found = groups.findIndex((group) => group.includes(page));
  return found === -1 ? 0 : found;
}

/** What a tap at ``x`` (0–1 across the page) does. */
export function tapAction(x: number, rtl: boolean): "previous" | "next" | "menu" {
  if (x < 0.3) return rtl ? "next" : "previous";
  if (x > 0.7) return rtl ? "previous" : "next";
  return "menu";
}
