/**
 * Typed URL search state with defaults that stay out of the URL: a route
 * validates to the non-default values only (so links need no search), and
 * pages resolve them against the defaults.
 */
type Parsers<T> = { [K in keyof T]: (value: unknown) => T[K] | undefined };

export function oneOf<const T extends string>(allowed: readonly T[]) {
  return (value: unknown): T | undefined =>
    typeof value === "string" && (allowed as readonly string[]).includes(value) ? (value as T) : undefined;
}

export function count(value: unknown): number | undefined {
  const number = typeof value === "number" ? value : typeof value === "string" && value !== "" ? Number(value) : NaN;
  return Number.isInteger(number) && number >= 0 ? number : undefined;
}

export function text(value: unknown): string | undefined {
  if (typeof value === "number") return String(value);
  return typeof value === "string" && value.trim() !== "" ? value : undefined;
}

export function searchSchema<T extends Record<string, unknown>>(defaults: T, parsers: Parsers<T>) {
  const clean = (values: Partial<T>): Partial<T> => {
    const out: Partial<T> = {};
    for (const key of Object.keys(parsers) as (keyof T)[]) {
      const value = values[key] === undefined ? undefined : parsers[key](values[key]);
      if (value !== undefined && value !== defaults[key]) out[key] = value;
    }
    return out;
  };
  return {
    validate: (raw: Record<string, unknown>): Partial<T> => clean(raw as Partial<T>),
    resolve: (search: Partial<T>): T => ({ ...defaults, ...search }),
    /** For navigate({ search }): the previous values with some changed. */
    update: (next: Partial<T>) => (previous: Partial<T>) => clean({ ...previous, ...next }),
  };
}
