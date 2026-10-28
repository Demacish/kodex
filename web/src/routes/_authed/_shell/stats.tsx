import { createFileRoute } from "@tanstack/react-router";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { api, type Schemas } from "@/api/client";
import { ErrorState, PageHeader } from "@/components/common/states";
import { Skeleton } from "@/components/ui/skeleton";
import { format } from "@/i18n";

export const Route = createFileRoute("/_authed/_shell/stats")({
  component: Stats,
});

type ReadingStats = Schemas["ReadingStatsOut"];

function Stats() {
  const { t } = useTranslation();
  const stats = api.useQuery("get", "/api/me/reading-stats");
  return (
    <div className="max-w-4xl space-y-6">
      <PageHeader title={t("readingStats.title")} description={t("readingStats.intro")} />
      {stats.isError ? (
        <ErrorState error={stats.error} onRetry={() => void stats.refetch()} />
      ) : !stats.data ? (
        <Skeleton className="h-96 rounded-xl" />
      ) : (
        <>
          <Tiles stats={stats.data} />
          <MonthChart months={stats.data.finished_by_month} />
          <Calendar days={stats.data.days} />
        </>
      )}
    </div>
  );
}

function Tile({ label, value, note }: { label: string; value: string; note?: string }) {
  return (
    <div className="rounded-xl border bg-card p-4">
      <div className="text-sm text-muted-foreground">{label}</div>
      <div className="mt-1 text-3xl font-semibold tracking-tight">{value}</div>
      {note && <div className="mt-1 text-xs text-muted-foreground">{note}</div>}
    </div>
  );
}

function Tiles({ stats }: { stats: ReadingStats }) {
  const { t } = useTranslation();
  const year = String(new Date().getUTCFullYear());
  const thisYear = stats.finished_by_month.filter((m) => m.month.startsWith(year)).reduce((sum, m) => sum + m.count, 0);
  return (
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
      <Tile label={t("readingStats.finishedThisYear")} value={format.number(thisYear)} note={t("readingStats.finishedTotal", { count: stats.finished_total })} />
      <Tile label={t("readingStats.inProgress")} value={format.number(stats.in_progress)} />
      <Tile label={t("readingStats.streak")} value={t("readingStats.days", { count: stats.current_streak })} note={t("readingStats.longest", { count: stats.longest_streak })} />
      <Tile label={t("readingStats.pages")} value={format.number(stats.pages)} note={t("readingStats.pagesNote")} />
    </div>
  );
}

function monthLabel(month: string, style: "short" | "long" = "short") {
  const [year, number] = month.split("-").map(Number);
  return format.date(new Date(Date.UTC(year!, number! - 1, 15)), style === "short" ? { month: "short" } : { month: "long", year: "numeric" });
}

/** Books finished per month: one series, columns from one baseline, a tooltip per column. */
function MonthChart({ months }: { months: ReadingStats["finished_by_month"] }) {
  const { t } = useTranslation();
  const [active, setActive] = useState<number | null>(null);
  const top = Math.max(1, ...months.map((m) => m.count));
  const ticks = top <= 4 ? Array.from({ length: top + 1 }, (_, i) => i) : [0, Math.round(top / 2), top];
  const height = 160;
  return (
    <section className="rounded-xl border bg-card p-5" aria-labelledby="stats-months">
      <h2 id="stats-months" className="text-lg font-semibold">{t("readingStats.perMonth")}</h2>
      <p className="mb-4 text-sm text-muted-foreground">{t("readingStats.perMonthIntro")}</p>
      <div className="relative flex gap-2" style={{ height: height + 24 }}>
        <div className="relative w-6 shrink-0 text-right text-xs tabular-nums text-muted-foreground" aria-hidden>
          {ticks.map((tick) => (
            <span key={tick} className="absolute right-0 -translate-y-1/2" style={{ top: height - (tick / top) * height }}>{tick}</span>
          ))}
        </div>
        <div className="relative flex-1">
          {ticks.map((tick) => (
            <div key={tick} className="absolute inset-x-0 border-t border-border" style={{ top: height - (tick / top) * height }} aria-hidden />
          ))}
          <ol className="absolute inset-x-0 top-0 flex items-end justify-between gap-1" style={{ height }}>
            {months.map((month, index) => (
              <li
                key={month.month}
                className="relative flex h-full flex-1 items-end justify-center outline-none"
                tabIndex={0}
                aria-label={t("readingStats.monthValue", { month: monthLabel(month.month, "long"), count: month.count })}
                onPointerEnter={() => setActive(index)}
                onPointerLeave={() => setActive(null)}
                onFocus={() => setActive(index)}
                onBlur={() => setActive(null)}
              >
                <span
                  className="w-full max-w-6 rounded-t bg-chart-1 transition-opacity"
                  style={{ height: (month.count / top) * height, opacity: active === null || active === index ? 1 : 0.55 }}
                />
                {active === index && (
                  <span role="tooltip" className="pointer-events-none absolute bottom-full mb-1 whitespace-nowrap rounded-md border bg-popover px-2 py-1 text-xs shadow-sm">
                    <strong className="font-semibold">{month.count}</strong> <span className="text-muted-foreground">{monthLabel(month.month, "long")}</span>
                  </span>
                )}
                <span className="absolute top-full mt-1.5 text-[11px] text-muted-foreground" aria-hidden>{monthLabel(month.month)}</span>
              </li>
            ))}
          </ol>
        </div>
      </div>
      <details className="mt-6 text-sm">
        <summary className="cursor-pointer text-muted-foreground">{t("readingStats.asTable")}</summary>
        <table className="mt-2 w-full max-w-xs">
          <thead><tr className="text-left text-muted-foreground"><th className="font-normal">{t("readingStats.month")}</th><th className="text-right font-normal">{t("readingStats.finished")}</th></tr></thead>
          <tbody>
            {months.map((m) => <tr key={m.month}><td>{monthLabel(m.month, "long")}</td><td className="text-right tabular-nums">{m.count}</td></tr>)}
          </tbody>
        </table>
      </details>
    </section>
  );
}

// Days are UTC days (backend: kodex/reading/stats.py).
const UTC_DAY: Intl.DateTimeFormatOptions = { dateStyle: "medium", timeZone: "UTC" };
const STEPS = [0, 1, 2, 3, 4] as const;
const STEP_FILL = ["var(--muted)", "color-mix(in oklch, var(--chart-1) 30%, var(--card))", "color-mix(in oklch, var(--chart-1) 55%, var(--card))", "color-mix(in oklch, var(--chart-1) 80%, var(--card))", "var(--chart-1)"];

function step(day: Schemas["ReadingDayOut"] | undefined, top: number): number {
  if (!day) return 0;
  const amount = day.pages || day.books;
  return Math.max(1, Math.min(4, Math.ceil((amount / top) * 4)));
}

/** The last year of reading, a week per column, darker for more pages. */
function Calendar({ days }: { days: ReadingStats["days"] }) {
  const { t } = useTranslation();
  const [active, setActive] = useState<{ x: number; y: number; text: string } | null>(null);
  const { weeks, top } = useMemo(() => {
    const byDate = new Map(days.map((d) => [d.date, d]));
    const today = new Date();
    const end = Date.UTC(today.getUTCFullYear(), today.getUTCMonth(), today.getUTCDate());
    // Weeks start on Monday; 53 columns end with this week.
    const weekday = (new Date(end).getUTCDay() + 6) % 7;
    const start = end - (52 * 7 + weekday) * 86_400_000;
    const columns: { date: string; day?: Schemas["ReadingDayOut"]; future: boolean }[][] = [];
    for (let time = start, i = 0; i < 53 * 7; time += 86_400_000, i += 1) {
      const date = new Date(time).toISOString().slice(0, 10);
      if (i % 7 === 0) columns.push([]);
      columns.at(-1)!.push({ date, day: byDate.get(date), future: time > end });
    }
    return { weeks: columns, top: Math.max(1, ...days.map((d) => d.pages || d.books)) };
  }, [days]);
  const cell = 12;
  const gap = 2;
  const describe = (date: string, day?: Schemas["ReadingDayOut"]) =>
    day ? t("readingStats.dayValue", { date: format.date(date, UTC_DAY), books: day.books, pages: day.pages }) : t("readingStats.dayNone", { date: format.date(date, UTC_DAY) });
  return (
    <section className="rounded-xl border bg-card p-5" aria-labelledby="stats-days">
      <h2 id="stats-days" className="text-lg font-semibold">{t("readingStats.daysTitle")}</h2>
      <p className="mb-4 text-sm text-muted-foreground">{t("readingStats.daysIntro", { count: days.length })}</p>
      <div className="relative overflow-x-auto pb-2">
        <svg
          width={weeks.length * (cell + gap)}
          height={7 * (cell + gap)}
          role="img"
          aria-label={t("readingStats.daysIntro", { count: days.length })}
          onPointerLeave={() => setActive(null)}
        >
          {weeks.map((week, x) => week.map((entry, y) => entry.future ? null : (
            <rect
              key={entry.date}
              x={x * (cell + gap)}
              y={y * (cell + gap)}
              width={cell}
              height={cell}
              rx={2}
              fill={STEP_FILL[step(entry.day, top)]}
              onPointerEnter={() => setActive({ x: x * (cell + gap), y: y * (cell + gap), text: describe(entry.date, entry.day) })}
            />
          )))}
        </svg>
        {active && (
          <span role="tooltip" className="pointer-events-none absolute -translate-x-1/2 -translate-y-full whitespace-nowrap rounded-md border bg-popover px-2 py-1 text-xs shadow-sm" style={{ left: active.x + cell / 2, top: active.y - 4 }}>
            {active.text}
          </span>
        )}
      </div>
      <div className="mt-2 flex items-center gap-1.5 text-xs text-muted-foreground" aria-hidden>
        {t("readingStats.less")}
        {STEPS.map((s) => <span key={s} className="size-3 rounded-sm" style={{ background: STEP_FILL[s] }} />)}
        {t("readingStats.more")}
      </div>
      {days.length > 0 && (
        <details className="mt-4 text-sm">
          <summary className="cursor-pointer text-muted-foreground">{t("readingStats.asTable")}</summary>
          <table className="mt-2 w-full max-w-sm">
            <thead><tr className="text-left text-muted-foreground"><th className="font-normal">{t("readingStats.date")}</th><th className="text-right font-normal">{t("readingStats.books")}</th><th className="text-right font-normal">{t("readingStats.pagesShort")}</th></tr></thead>
            <tbody>
              {[...days].reverse().map((d) => (
                <tr key={d.date}><td>{format.date(d.date, UTC_DAY)}</td><td className="text-right tabular-nums">{d.books}</td><td className="text-right tabular-nums">{d.pages}</td></tr>
              ))}
            </tbody>
          </table>
        </details>
      )}
    </section>
  );
}
