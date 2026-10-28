import { ArrowDownWideNarrow, ArrowUpNarrowWide } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";

export const READ_STATUSES = ["all", "unread", "in_progress", "read"] as const;
export type ReadStatus = (typeof READ_STATUSES)[number];

export interface ListState<S extends string> {
  sort: S;
  order: "asc" | "desc";
  status: ReadStatus;
}

export function ListControls<S extends string>({ sorts, state, onChange, showStatus = true }: {
  sorts: readonly S[];
  state: ListState<S>;
  onChange: (next: Partial<ListState<S>>) => void;
  showStatus?: boolean;
}) {
  const { t } = useTranslation();
  return (
    <div className="mb-4 flex flex-wrap items-center gap-2">
      <Select value={state.sort} onValueChange={(value) => onChange({ sort: value as S })}>
        <SelectTrigger size="sm" aria-label={t("list.sortBy")} className="min-w-36">
          <SelectValue>{(value: string) => t(`list.sorts.${value as "title"}`)}</SelectValue>
        </SelectTrigger>
        <SelectContent>
          {sorts.map((sort) => (
            <SelectItem key={sort} value={sort}>
              {t(`list.sorts.${sort as "title"}`)}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <Button
        variant="outline"
        size="icon-sm"
        onClick={() => onChange({ order: state.order === "asc" ? "desc" : "asc" })}
        aria-label={state.order === "asc" ? t("list.ascending") : t("list.descending")}
        title={state.order === "asc" ? t("list.ascending") : t("list.descending")}
      >
        {state.order === "asc" ? <ArrowUpNarrowWide aria-hidden /> : <ArrowDownWideNarrow aria-hidden />}
      </Button>
      {showStatus && (
        <ToggleGroup
          value={[state.status]}
          onValueChange={(value: string[]) => value[0] && onChange({ status: value[0] as ReadStatus })}
          variant="outline"
          size="sm"
          aria-label={t("list.readStatus")}
        >
          {READ_STATUSES.map((status) => (
            <ToggleGroupItem key={status} value={status}>
              {t(`list.status.${status}`)}
            </ToggleGroupItem>
          ))}
        </ToggleGroup>
      )}
    </div>
  );
}

export function Pager({ offset, limit, hasMore, onChange }: {
  offset: number;
  limit: number;
  hasMore: boolean;
  onChange: (offset: number) => void;
}) {
  const { t } = useTranslation();
  if (offset === 0 && !hasMore) return null;
  return (
    <nav aria-label={t("list.pages")} className="mt-6 flex items-center justify-center gap-3 text-sm">
      <Button variant="outline" size="sm" disabled={offset === 0} onClick={() => onChange(Math.max(0, offset - limit))}>
        {t("list.previous")}
      </Button>
      <span className="text-muted-foreground">{t("list.page", { page: Math.floor(offset / limit) + 1 })}</span>
      <Button variant="outline" size="sm" disabled={!hasMore} onClick={() => onChange(offset + limit)}>
        {t("list.next")}
      </Button>
    </nav>
  );
}
