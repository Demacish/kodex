import { createFileRoute } from "@tanstack/react-router";
import { CircleCheck, CircleDashed } from "lucide-react";
import { useTranslation } from "react-i18next";

import { api, type Schemas } from "@/api/client";
import { ErrorState, PageHeader } from "@/components/common/states";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";

export const Route = createFileRoute("/_authed/_shell/admin/integrations")({
  component: Integrations,
});

const GROUPS = ["login", "metadata", "search", "notifications", "delivery", "ai", "downloads", "sync"] as const;

/** What's set up, and which environment variables set up the rest. */
function Integrations() {
  const { t } = useTranslation();
  const items = api.useQuery("get", "/api/admin/integrations");
  return (
    <div>
      <PageHeader title={t("admin.nav.integrations")} description={t("integrations.intro")} />
      {items.isError ? (
        <ErrorState error={items.error} onRetry={() => void items.refetch()} />
      ) : items.isPending ? (
        <Skeleton className="h-64 rounded-xl" />
      ) : (
        <div className="space-y-6">
          {GROUPS.map((group) => {
            const inGroup = items.data.filter((i) => i.group === group);
            if (inGroup.length === 0) return null;
            return (
              <section key={group} aria-labelledby={`int-${group}`}>
                <h2 id={`int-${group}`} className="mb-2 text-sm font-semibold text-muted-foreground">{t(`integrations.groups.${group}`)}</h2>
                <ul className="grid gap-3 sm:grid-cols-2">{inGroup.map((item) => <Item key={item.key} item={item} />)}</ul>
              </section>
            );
          })}
        </div>
      )}
    </div>
  );
}

function Item({ item }: { item: Schemas["IntegrationOut"] }) {
  const { t } = useTranslation();
  return (
    <li className="rounded-xl border bg-card p-4">
      <div className="flex items-center gap-2">
        {item.configured ? <CircleCheck className="size-4 text-emerald-600 dark:text-emerald-400" aria-hidden /> : <CircleDashed className="size-4 text-muted-foreground" aria-hidden />}
        <span className="font-medium">{t(`integrations.items.${item.key}.name`, { defaultValue: item.key })}</span>
        <Badge variant={item.configured ? "secondary" : "outline"} className="ml-auto">
          {item.configured ? (item.host ?? t("integrations.configured")) : t("common.notConfigured")}
        </Badge>
      </div>
      <p className="mt-1 text-sm text-muted-foreground">{t(`integrations.items.${item.key}.what`, { defaultValue: "" })}</p>
      {!item.configured && (
        <p className="mt-2 text-xs text-muted-foreground">
          {t("integrations.setWith")} {item.env.map((name) => <code key={name} className="mr-1 rounded bg-muted px-1">{name}</code>)}
        </p>
      )}
    </li>
  );
}
