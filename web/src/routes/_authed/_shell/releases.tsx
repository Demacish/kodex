import { useQueryClient } from "@tanstack/react-query";
import { createFileRoute, Link } from "@tanstack/react-router";
import { CalendarDays, EyeOff, Inbox } from "lucide-react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { api, type Schemas } from "@/api/client";
import { EmptyState, ErrorState, PageHeader } from "@/components/common/states";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { format } from "@/i18n";
import { oneOf, searchSchema } from "@/lib/search";

type Event = Schemas["ReleaseEventOut"];
const STATUSES = ["all", "unreleased", "released", "owned"] as const;
const search = searchSchema({ status: "all" as (typeof STATUSES)[number] }, { status: oneOf(STATUSES) });
const VARIANT = { unreleased: "secondary", released: "default", owned: "outline" } as const;

export const Route = createFileRoute("/_authed/_shell/releases")({
  validateSearch: search.validate,
  component: Releases,
});

function monthKey(event: Event): string {
  return event.store_date ? event.store_date.slice(0, 7) : "";
}

function Releases() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const { status } = search.resolve(Route.useSearch());
  const navigate = Route.useNavigate();
  const events = api.useQuery("get", "/api/releases", { params: { query: status === "all" ? {} : { status } } });
  const dismiss = api.useMutation("post", "/api/releases/{event_id}/dismiss", {
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["get", "/api/releases"] }),
  });
  const request = api.useMutation("post", "/api/requests");
  const want = async (event: Event) => {
    try {
      await request.mutateAsync({ body: { title: `${event.series_title} #${event.issue_number ?? ""}`.trim(), media_type: "series" } });
      toast.success(t("releases.requested"));
    } catch {
      toast.error(t("common.errorGeneric"));
    }
  };

  const groups = new Map<string, Event[]>();
  for (const event of events.data ?? []) groups.set(monthKey(event), [...(groups.get(monthKey(event)) ?? []), event]);

  return (
    <div>
      <PageHeader title={t("nav.releases")} description={t("releases.intro")} />
      <ToggleGroup value={[status]} onValueChange={(v: string[]) => v[0] && navigate({ search: search.update({ status: v[0] as (typeof STATUSES)[number] }) })} variant="outline" size="sm" className="mb-6 flex-wrap">
        {STATUSES.map((s) => <ToggleGroupItem key={s} value={s}>{t(`releases.status.${s}`)}</ToggleGroupItem>)}
      </ToggleGroup>
      {events.isError ? (
        <ErrorState error={events.error} onRetry={() => void events.refetch()} />
      ) : events.isPending ? (
        <div className="space-y-2">{[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-16 rounded-xl" />)}</div>
      ) : events.data.length === 0 ? (
        <EmptyState icon={CalendarDays} title={t("releases.none")}>{t("releases.noneText")}</EmptyState>
      ) : (
        <div className="space-y-8">
          {[...groups].map(([month, items]) => (
            <section key={month || "unknown"} aria-labelledby={`month-${month || "unknown"}`}>
              <h2 id={`month-${month || "unknown"}`} className="mb-3 text-sm font-semibold text-muted-foreground capitalize">
                {month ? format.date(`${month}-01`, { month: "long", year: "numeric" }) : t("releases.noDate")}
              </h2>
              <ul className="divide-y rounded-xl border bg-card">
                {items.map((event) => (
                  <li key={event.id} className="flex flex-wrap items-center gap-3 p-3">
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <Link to="/series/$seriesId" params={{ seriesId: event.series_id }} className="font-medium hover:text-primary-text">
                          {event.series_title}
                        </Link>
                        {event.issue_number && <span className="text-muted-foreground">#{event.issue_number}</span>}
                        <Badge variant={VARIANT[event.status]}>{t(`releases.status.${event.status}`)}</Badge>
                      </div>
                      <div className="text-xs text-muted-foreground">
                        {[event.title, event.store_date && format.date(event.store_date)].filter(Boolean).join(" · ")}
                      </div>
                    </div>
                    {event.status === "owned" && event.owned_book_id ? (
                      <Button variant="outline" size="sm" render={<Link to="/books/$bookId" params={{ bookId: event.owned_book_id }} />}>{t("releases.open")}</Button>
                    ) : (
                      <span className="flex gap-1">
                        {event.status === "released" && (
                          <Button variant="outline" size="sm" onClick={() => void want(event)} disabled={request.isPending}>
                            <Inbox aria-hidden />
                            {t("releases.request")}
                          </Button>
                        )}
                        <Button variant="ghost" size="sm" onClick={() => dismiss.mutate({ params: { path: { event_id: event.id } } })} aria-label={t("releases.hide", { title: event.series_title })}>
                          <EyeOff aria-hidden />
                        </Button>
                      </span>
                    )}
                  </li>
                ))}
              </ul>
            </section>
          ))}
        </div>
      )}
    </div>
  );
}
