import { createFileRoute, Link } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";

import { api } from "@/api/client";
import { EmptyState, ErrorState, PageHeader } from "@/components/common/states";
import { LibraryCard } from "@/components/library/LibraryCard";
import { Skeleton } from "@/components/ui/skeleton";
import { useAccount } from "@/lib/account";

export const Route = createFileRoute("/_authed/_shell/libraries/")({
  component: Libraries,
});

function Libraries() {
  const { t } = useTranslation();
  const account = useAccount();
  const libraries = api.useQuery("get", "/api/libraries");
  return (
    <div>
      <PageHeader title={t("nav.libraries")} />
      {libraries.isError ? (
        <ErrorState error={libraries.error} onRetry={() => void libraries.refetch()} />
      ) : libraries.isPending ? (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {[0, 1, 2].map((i) => <Skeleton key={i} className="h-20 rounded-xl" />)}
        </div>
      ) : libraries.data.length === 0 ? (
        <EmptyState title={t("home.noLibraries")}>
          {account.is_admin ? <Link to="/admin/libraries" className="text-primary-text hover:underline">{t("home.createLibrary")}</Link> : t("home.noLibrariesUser")}
        </EmptyState>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {libraries.data.map((library) => <LibraryCard key={library.id} library={library} />)}
        </div>
      )}
    </div>
  );
}
