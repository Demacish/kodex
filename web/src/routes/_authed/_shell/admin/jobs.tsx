import { createFileRoute } from "@tanstack/react-router";
import { CircleCheck, CircleDashed, CircleX, Loader2, Plus } from "lucide-react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { api, fetchClient, type Schemas } from "@/api/client";
import { EmptyState, ErrorState, PageHeader } from "@/components/common/states";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { format } from "@/i18n";

export const Route = createFileRoute("/_authed/_shell/admin/jobs")({
  component: Jobs,
});

const ICONS = { queued: CircleDashed, started: Loader2, finished: CircleCheck, failed: CircleX, canceled: CircleX } as const;
const TONE = { queued: "text-muted-foreground", started: "text-primary-text animate-spin", finished: "text-emerald-600 dark:text-emerald-400", failed: "text-destructive", canceled: "text-muted-foreground" } as const;

function jobText(job: Schemas["JobOut"], t: (key: string, options?: Record<string, unknown>) => string): string {
  const what = t(`jobs.kinds.${job.kind}`, { defaultValue: "" });
  if (!what) return job.label;
  return job.subject ? `${what}: ${job.subject}` : what;
}

/** What the workers are doing and have just done; refreshes every few seconds. */
function Jobs() {
  const { t } = useTranslation();
  const jobs = api.useQuery("get", "/api/jobs", {}, { refetchInterval: 3000 });
  const checkReleases = async () => {
    const { error } = await fetchClient.POST("/api/series/check-releases");
    if (error) toast.error(t("common.errorGeneric"));
    else toast.success(t("jobs.releaseQueued"));
  };
  return (
    <div>
      <PageHeader
        title={t("admin.nav.jobs")}
        description={t("jobs.intro")}
        actions={<Button size="sm" variant="outline" onClick={() => void checkReleases()}><Plus aria-hidden />{t("jobs.checkReleases")}</Button>}
      />
      {jobs.isError ? (
        <ErrorState error={jobs.error} onRetry={() => void jobs.refetch()} />
      ) : jobs.isPending ? (
        <Skeleton className="h-48 rounded-xl" />
      ) : jobs.data.length === 0 ? (
        <EmptyState icon={CircleCheck} title={t("jobs.none")} />
      ) : (
        <ul className="divide-y rounded-xl border bg-card" aria-live="polite">
          {jobs.data.map((job) => {
            const status = (job.status in ICONS ? job.status : "queued") as keyof typeof ICONS;
            const Icon = ICONS[status];
            const when = job.ended_at ?? job.started_at ?? job.enqueued_at;
            return (
              <li key={job.id} className="flex items-start gap-3 px-4 py-3">
                <Icon className={`mt-0.5 size-4 shrink-0 ${TONE[status]}`} aria-hidden />
                <div className="min-w-0 flex-1">
                  <div className="text-sm font-medium">{jobText(job, t as never)}</div>
                  <div className="text-xs text-muted-foreground">
                    {t(`jobs.status.${status}`)} · {job.queue}
                    {when && ` · ${format.relative(when)}`}
                    {job.started_at && job.ended_at && ` · ${t("jobs.took", { seconds: Math.max(1, Math.round((new Date(job.ended_at).getTime() - new Date(job.started_at).getTime()) / 1000)) })}`}
                  </div>
                  {job.error && <p className="mt-1 text-xs break-words text-destructive">{job.error}</p>}
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
