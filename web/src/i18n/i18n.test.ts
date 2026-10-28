import { describe, expect, it } from "vitest";

import en from "./en.json";
import sv from "./sv.json";

function keys(value: unknown, prefix = ""): string[] {
  if (value === null || typeof value !== "object") return [prefix];
  return Object.entries(value as Record<string, unknown>).flatMap(([key, inner]) => keys(inner, prefix ? `${prefix}.${key}` : key));
}

function placeholders(text: string): string[] {
  return [...text.matchAll(/\{\{(\w+)\}\}/g)].map((m) => m[1]!).sort();
}

describe("translations", () => {
  it("have the same keys in Swedish and English", () => {
    expect(keys(en).sort()).toEqual(keys(sv).sort());
  });

  it("use the same placeholders in both languages", () => {
    const lookup = (root: unknown, path: string) => path.split(".").reduce<unknown>((o, k) => (o as Record<string, unknown>)[k], root);
    for (const key of keys(sv)) {
      expect(placeholders(String(lookup(en, key))), key).toEqual(placeholders(String(lookup(sv, key))));
    }
  });
});
