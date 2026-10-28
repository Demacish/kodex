import { useQueryClient } from "@tanstack/react-query";
import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { BookOpen, FileUp, Layers, Plus, Sparkles } from "lucide-react";
import { useRef, type ChangeEvent } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { api, csrfToken, errorMessage, type Schemas } from "@/api/client";
import { CollectionCard } from "@/components/collections/CollectionCard";
import { CollectionDialog, GenerateCollectionDialog, StoryArcImportDialog } from "@/components/collections/CollectionDialog";
import { CoverGridSkeleton, EmptyState, ErrorState, PageHeader } from "@/components/common/states";
import { CoverGrid } from "@/components/library/CoverGrid";
import { Button } from "@/components/ui/button";
import { useAccount } from "@/lib/account";

export const Route = createFileRoute("/_authed/_shell/collections/")({
  component: Collections,
});

function Collections() {
  const { t } = useTranslation();
  const account = useAccount();
  const collections = api.useQuery("get", "/api/collections");
  return (
    <div>
      <PageHeader
        title={t("nav.collections")}
        description={t("collections.intro")}
        actions={
          account.is_admin && (
            <>
              <CblImport />
              <StoryArcImportDialog trigger={<Button variant="outline" size="sm"><BookOpen aria-hidden />{t("collections.fromArc")}</Button>} />
              <GenerateCollectionDialog trigger={<Button variant="outline" size="sm"><Sparkles aria-hidden />{t("collections.generate")}</Button>} />
              <CollectionDialog trigger={<Button size="sm"><Plus aria-hidden />{t("collections.new")}</Button>} />
            </>
          )
        }
      />
      {collections.isError ? (
        <ErrorState error={collections.error} onRetry={() => void collections.refetch()} />
      ) : collections.isPending ? (
        <CoverGridSkeleton />
      ) : collections.data.length === 0 ? (
        <EmptyState icon={Layers} title={t("collections.none")} />
      ) : (
        <CoverGrid>
          {collections.data.map((collection) => (
            <li key={collection.id}>
              <CollectionCard collection={collection} />
            </li>
          ))}
        </CoverGrid>
      )}
    </div>
  );
}

/** A reading list file (.cbl) in, as a collection of the books that are here. */
function CblImport() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const input = useRef<HTMLInputElement>(null);
  const upload = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.currentTarget.files?.[0];
    event.currentTarget.value = "";
    if (!file) return;
    const form = new FormData();
    form.append("file", file);
    const response = await fetch("/api/collections/import-cbl", {
      method: "POST", body: form, credentials: "same-origin", headers: { "X-CSRF-Token": csrfToken() ?? "" },
    });
    const body = (await response.json().catch(() => ({}))) as Schemas["CblImportOut"];
    if (!response.ok) return void toast.error(errorMessage(body, t("common.errorGeneric")));
    toast.success(t("collections.cblImported", { count: body.matched, missing: body.missing.length }));
    await queryClient.invalidateQueries({ queryKey: ["get", "/api/collections"] });
    await navigate({ to: "/collections/$collectionId", params: { collectionId: body.collection.id } });
  };
  return (
    <>
      <input ref={input} type="file" accept=".cbl,application/xml,text/xml" className="hidden" onChange={(e) => void upload(e)} aria-hidden tabIndex={-1} />
      <Button variant="outline" size="sm" onClick={() => input.current?.click()}><FileUp aria-hidden />{t("collections.importCbl")}</Button>
    </>
  );
}
