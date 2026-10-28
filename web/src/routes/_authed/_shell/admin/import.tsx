import { createFileRoute, Link } from "@tanstack/react-router";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { api } from "@/api/client";
import { CblLink } from "@/components/admin/CblLink";
import { CsvImport } from "@/components/admin/CsvImport";
import { LocgLink } from "@/components/admin/LocgLink";
import { Sorting } from "@/components/admin/Sorting";
import { PageHeader } from "@/components/common/states";

export const Route = createFileRoute("/_authed/_shell/admin/import")({
  component: Import,
});

function Part({ title, description, children }: { title: string; description: string; children: ReactNode }) {
  return (
    <section className="rounded-xl border bg-card p-5" aria-label={title}>
      <h2 className="text-lg font-semibold">{title}</h2>
      <p className="mb-4 text-sm text-muted-foreground">{description}</p>
      {children}
    </section>
  );
}

/** Bringing things in: the intake's sorting, a CSV pull list, a CBL reading list. Uploads are per library. */
function Import() {
  const { t } = useTranslation();
  const libraries = api.useQuery("get", "/api/libraries");
  const intake = libraries.data?.find((library) => library.library_type === "mixed");
  return (
    <div className="space-y-6">
      <PageHeader title={t("admin.nav.import")} description={<>{t("importPage.intro")} <Link to="/admin/libraries" className="text-primary-text hover:underline">{t("importPage.uploadLink")}</Link></>} />
      <Part title={t("importPage.sortTitle")} description={t("importPage.sortIntro")}>
        {intake ? <Sorting intake={intake} /> : <p className="text-sm text-muted-foreground">{t("importPage.noIntake")}</p>}
      </Part>
      <Part title={t("importPage.csvTitle")} description={t("importPage.csvIntro")}>
        <CsvImport />
      </Part>
      <Part title={t("importPage.cblTitle")} description={t("importPage.cblIntro")}>
        <CblLink />
      </Part>
      <Part title={t("importPage.locgTitle")} description={t("importPage.locgIntro")}>
        <LocgLink />
      </Part>
    </div>
  );
}
