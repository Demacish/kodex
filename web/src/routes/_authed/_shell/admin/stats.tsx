import { createFileRoute } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";

import { api } from "@/api/client";
import { ErrorState, PageHeader } from "@/components/common/states";
import { Skeleton } from "@/components/ui/skeleton";
import { format } from "@/i18n";

export const Route = createFileRoute("/_authed/_shell/admin/stats")({
  component: Stats,
});

const TYPES = ["comics", "manga", "ebooks", "mixed"] as const;
const COLORS = ["var(--chart-1)", "var(--chart-2)", "var(--chart-3)", "var(--chart-4)"];

function Tile({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-xl border bg-card p-4">
      <div className="text-sm text-muted-foreground">{label}</div>
      <div className="mt-1 truncate text-2xl font-semibold tabular-nums">{value}</div>
      {hint && <div className="mt-1 truncate text-xs text-muted-foreground">{hint}</div>}
    </div>
  );
}

/** One horizontal bar per category, labelled directly, no legend needed. */
function Bars({ title, rows }: { title: string; rows: { label: string; value: number; color: string }[] }) {
  const max = Math.max(1, ...rows.map((r) => r.value));
  return (
    <figure className="rounded-xl border bg-card p-4">
      <figcaption className="mb-4 text-sm font-semibold">{title}</figcaption>
      <ul className="space-y-3">
        {rows.map((row) => (
          <li key={row.label} className="flex items-center gap-3">
            <span className="w-24 shrink-0 truncate text-sm text-muted-foreground">{row.label}</span>
            <span className="h-3 flex-1 rounded-full bg-muted">
              <span className="block h-3 rounded-r-[4px]" style={{ width: `${(row.value / max) * 100}%`, background: row.color }} />
            </span>
            <span className="w-14 text-right text-sm tabular-nums">{format.number(row.value)}</span>
          </li>
        ))}
      </ul>
    </figure>
  );
}

function Stats() {
  const { t } = useTranslation();
  const stats = api.useQuery("get", "/api/stats");
  if (stats.isError) return <ErrorState error={stats.error} onRetry={() => void stats.refetch()} />;
  if (!stats.data) return <Skeleton className="h-64 rounded-xl" />;
  const s = stats.data;
  const typeRows = (counts: Record<string, number>) =>
    TYPES.filter((type) => counts[type]).map((type, i) => ({ label: t(`adminLibraries.types.${type}`), value: counts[type] ?? 0, color: COLORS[i]! }));
  return (
    <div>
      <PageHeader title={t("admin.nav.stats")} />
      <div className="mb-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Tile label={t("stats.books")} value={format.number(s.total_books)} />
        <Tile label={t("stats.size")} value={format.bytes(s.total_size_bytes)} />
        <Tile label={t("stats.finished")} value={format.number(s.reading_status.finished)} hint={t("stats.inProgress", { count: s.reading_status.in_progress })} />
        <Tile label={t("stats.latest")} value={s.latest_added?.title ?? "–"} hint={s.latest_added ? format.relative(s.latest_added.added_at) : undefined} />
      </div>
      <div className="grid gap-4 lg:grid-cols-3">
        <Bars title={t("stats.booksByType")} rows={typeRows(s.books_by_type)} />
        <Bars title={t("stats.seriesByType")} rows={typeRows(s.series_by_type)} />
        <Bars title={t("stats.reading")} rows={[
          { label: t("list.status.unread"), value: s.reading_status.unread, color: COLORS[0]! },
          { label: t("list.status.in_progress"), value: s.reading_status.in_progress, color: COLORS[1]! },
          { label: t("list.status.read"), value: s.reading_status.finished, color: COLORS[2]! },
        ]} />
      </div>
    </div>
  );
}
