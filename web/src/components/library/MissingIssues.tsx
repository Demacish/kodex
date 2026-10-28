import { useQueryClient } from "@tanstack/react-query";
import { Check, Plus } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { api, errorMessage, fetchClient } from "@/api/client";
import { Button } from "@/components/ui/button";

const SHOWN = 12;

/** The series' missing numbers, each one a request away (with the acquisition add-on, it then arrives on its own). */
export function MissingIssues({ seriesId, gaps }: { seriesId: number; gaps: string[] }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const mine = api.useQuery("get", "/api/requests/mine");
  const acquire = api.useQuery("get", "/api/acquire");
  if (gaps.length === 0) return null;
  const numbers = expand(gaps);
  const asked = new Set((mine.data ?? []).filter((r) => r.series_id === seriesId && r.status !== "rejected").map((r) => r.issue_number));
  const request = async (number: number) => {
    const { error } = await fetchClient.POST("/api/requests", { body: { title: "", media_type: "series", series_id: seriesId, issue_number: number } });
    if (error) return void toast.error(errorMessage(error, t("common.errorGeneric")));
    toast.success(t("missingIssues.requested", { number }));
    await queryClient.invalidateQueries({ queryKey: ["get", "/api/requests/mine"] });
  };
  return (
    <div className="space-y-2 text-xs text-muted-foreground">
      <p>
        {t("series.gaps", { count: gaps.length, numbers: gaps.slice(0, SHOWN).map((g) => `#${g}`).join(", ") + (gaps.length > SHOWN ? "…" : "") })}{" "}
        <button type="button" className="underline" onClick={() => setOpen(!open)} aria-expanded={open}>{open ? t("missingIssues.hide") : t("missingIssues.request")}</button>
      </p>
      {open && (
        <>
          <div className="flex flex-wrap gap-1.5" role="group" aria-label={t("missingIssues.request")}>
            {numbers.map((number) =>
              asked.has(number) ? (
                <Button key={number} size="xs" variant="secondary" disabled><Check aria-hidden />#{number}</Button>
              ) : (
                <Button key={number} size="xs" variant="outline" onClick={() => void request(number)} aria-label={t("missingIssues.requestNumber", { number })}>
                  <Plus aria-hidden />#{number}
                </Button>
              ),
            )}
          </div>
          <p>{acquire.data?.enabled ? t("missingIssues.automatic") : t("missingIssues.manual")}</p>
        </>
      )}
    </div>
  );
}

/** "4–7" and "9" as 4, 5, 6, 7, 9; at most 50 of them. */
function expand(gaps: string[]): number[] {
  const out: number[] = [];
  for (const gap of gaps) {
    const [from, to] = gap.split("–").map(Number);
    for (let n = from!; n <= (to ?? from!) && out.length < 50; n += 1) out.push(n);
  }
  return out;
}
