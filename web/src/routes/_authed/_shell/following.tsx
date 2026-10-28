import { createFileRoute, Link } from "@tanstack/react-router";
import { BellOff, CalendarDays } from "lucide-react";
import { useTranslation } from "react-i18next";

import { api } from "@/api/client";
import { CoverGridSkeleton, EmptyState, ErrorState, PageHeader } from "@/components/common/states";
import { CoverGrid } from "@/components/library/CoverGrid";
import { SeriesCard } from "@/components/library/SeriesCard";
import { Button } from "@/components/ui/button";

export const Route = createFileRoute("/_authed/_shell/following")({
  component: Following,
});

function Following() {
  const { t } = useTranslation();
  const series = api.useQuery("get", "/api/series", { params: { query: { following: true, limit: 1000 } } });
  return (
    <div>
      <PageHeader
        title={t("nav.following")}
        description={t("following.intro")}
        actions={
          <Button variant="outline" size="sm" render={<Link to="/releases" />}>
            <CalendarDays aria-hidden />
            {t("nav.releases")}
          </Button>
        }
      />
      {series.isError ? (
        <ErrorState error={series.error} onRetry={() => void series.refetch()} />
      ) : series.isPending ? (
        <CoverGridSkeleton />
      ) : series.data.length === 0 ? (
        <EmptyState icon={BellOff} title={t("following.none")}>{t("following.noneText")}</EmptyState>
      ) : (
        <CoverGrid>
          {series.data.map((item) => (
            <li key={item.id}>
              <SeriesCard series={item} />
            </li>
          ))}
        </CoverGrid>
      )}
    </div>
  );
}
