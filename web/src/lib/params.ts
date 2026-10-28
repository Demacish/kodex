import { notFound } from "@tanstack/react-router";

/** Route params for numeric ids: anything else is a 404. */
export function idParam<K extends string>(key: K) {
  return {
    parse: (params: Record<K, string>) => {
      const id = Number(params[key]);
      if (!Number.isInteger(id) || id < 0) throw notFound();
      return { [key]: id } as Record<K, number>;
    },
    stringify: (params: Record<K, number>) => ({ [key]: String(params[key]) }) as Record<K, string>,
  };
}
