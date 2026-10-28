import { describe, expect, it } from "vitest";

import { groupOf, spreads, tapAction, widthStep } from "./layout";

describe("spreads", () => {
  it("pairs pages after a cover shown alone", () => {
    expect(spreads(6, [], true)).toEqual([[0], [1, 2], [3, 4], [5]]);
    expect(spreads(4, [], false)).toEqual([[0, 1], [2, 3]]);
  });

  it("shows wide pages alone and keeps pairing after them", () => {
    const sizes: [number, number][] = [[100, 150], [100, 150], [300, 150], [100, 150], [100, 150]];
    expect(spreads(5, sizes, false)).toEqual([[0, 1], [2], [3, 4]]);
    expect(spreads(5, sizes, true)).toEqual([[0], [1], [2], [3, 4]]);
  });

  it("finds the group of a page", () => {
    const groups = spreads(6, [], true);
    expect(groupOf(groups, 4)).toBe(2);
    expect(groupOf(groups, 99)).toBe(0);
  });
});

describe("tap zones", () => {
  it("swap sides when reading right to left", () => {
    expect(tapAction(0.1, false)).toBe("previous");
    expect(tapAction(0.9, false)).toBe("next");
    expect(tapAction(0.1, true)).toBe("next");
    expect(tapAction(0.5, true)).toBe("menu");
  });
});

describe("widthStep", () => {
  it("rounds up to the server's steps", () => {
    expect(widthStep(1000)).toBe(1080);
    expect(widthStep(10_000)).toBe(3840);
  });
});
