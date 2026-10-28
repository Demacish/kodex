/** Gaps in a run of issue numbers: the whole numbers missing between the
 * lowest and highest, as ranges ("4", "7–9"). */
export function numberGaps(numbers: (number | null | undefined)[]): string[] {
  const whole = [...new Set(numbers.filter((n): n is number => n != null && Number.isInteger(n) && n >= 0))].sort((a, b) => a - b);
  const gaps: string[] = [];
  for (let i = 1; i < whole.length; i += 1) {
    const from = whole[i - 1]! + 1;
    const to = whole[i]! - 1;
    if (to >= from) gaps.push(from === to ? String(from) : `${from}–${to}`);
  }
  return gaps;
}
