import { useQueryClient } from "@tanstack/react-query";
import { FileCode2, Play, ScanSearch, SkipForward } from "lucide-react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { api, errorMessage, fetchClient, type Schemas } from "@/api/client";
import { EmptyState } from "@/components/common/states";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

const TYPES = ["comics", "manga", "ebooks"] as const;

/** The sorting assistant: what's in the intake library goes to the right one. */
export function Sorting({ intake }: { intake: Schemas["LibraryOut"] }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const items = api.useQuery("get", "/api/sorting", {}, { refetchInterval: 5000 });
  const refresh = () => queryClient.invalidateQueries({ queryKey: ["get", "/api/sorting"] });
  const run = async (call: () => Promise<{ error?: unknown }>, done: string) => {
    const { error } = await call();
    if (error) toast.error(errorMessage(error, t("common.errorGeneric")));
    else toast.success(done);
    await refresh();
  };
  const query = { params: { query: { library_id: intake.id } } };
  const pending = (items.data ?? []).filter((item) => item.status === "pending" || item.status === "resolved");
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-2">
        <Button size="sm" onClick={() => void run(() => fetchClient.POST("/api/sorting/scan", query), t("importPage.sortScanQueued"))}><ScanSearch aria-hidden />{t("importPage.sortScan")}</Button>
        <Button size="sm" variant="outline" onClick={() => void run(() => fetchClient.POST("/api/sorting/apply", query), t("importPage.sortApplyQueued"))}><Play aria-hidden />{t("importPage.sortApply")}</Button>
        <Button size="sm" variant="ghost" onClick={() => void run(() => fetchClient.POST("/api/sorting/write-comicinfo", query), t("importPage.sortComicInfoQueued"))}><FileCode2 aria-hidden />{t("importPage.sortComicInfo")}</Button>
      </div>
      {pending.length === 0 ? (
        <EmptyState title={t("importPage.sortNone")} />
      ) : (
        <ul className="divide-y rounded-lg border">
          {pending.map((item) => (
            <li key={item.id} className="flex flex-wrap items-center gap-3 px-3 py-2 text-sm">
              <span className="min-w-0 flex-1">
                <span className="block truncate font-medium" title={item.source_path}>{item.source_path}</span>
                <span className="block truncate text-xs text-muted-foreground">{item.detected_reason}</span>
              </span>
              {item.apply_error && <Badge variant="destructive">{item.apply_error}</Badge>}
              <Select
                value={item.resolved_type ?? item.detected_type ?? ""}
                onValueChange={(value) => void run(() => fetchClient.POST("/api/sorting/{item_id}/resolve", { params: { path: { item_id: item.id } }, body: { resolved_type: value as never } }), t("common.saved"))}
              >
                <SelectTrigger size="sm" className="w-32" aria-label={t("importPage.sortTo")}>
                  <SelectValue placeholder={t("importPage.sortUnknown")}>{(v: string) => (v ? t(`adminLibraries.types.${v as "comics"}`) : t("importPage.sortUnknown"))}</SelectValue>
                </SelectTrigger>
                <SelectContent>
                  {TYPES.map((type) => <SelectItem key={type} value={type}>{t(`adminLibraries.types.${type}`)}</SelectItem>)}
                </SelectContent>
              </Select>
              <Button size="icon-sm" variant="ghost" aria-label={t("importPage.sortSkip")} onClick={() => void run(() => fetchClient.POST("/api/sorting/{item_id}/skip", { params: { path: { item_id: item.id } } }), t("importPage.sortSkipped"))}>
                <SkipForward aria-hidden />
              </Button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
