import { useNavigate } from "@tanstack/react-router";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { errorMessage, fetchClient, type Schemas } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

/** A League of Comic Geeks event, by its address, becomes a story arc collection. */
export function LocgLink() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [found, setFound] = useState<Schemas["LocgPreviewOut"] | null>(null);
  const preview = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const url = String(new FormData(event.currentTarget).get("url") ?? "").trim();
    const { data, error } = await fetchClient.POST("/api/leagueofcomicgeeks/preview", { body: { url } });
    if (error) return void toast.error(errorMessage(error, t("common.errorGeneric")));
    setFound(data ?? null);
  };
  const link = async () => {
    if (!found) return;
    const { data, error } = await fetchClient.POST("/api/leagueofcomicgeeks/link", { body: found });
    if (error || !data) return void toast.error(errorMessage(error, t("common.errorGeneric")));
    toast.success(t("importPage.cblLinked", { name: found.name }));
    if (data.collection_id != null) await navigate({ to: "/collections/$collectionId", params: { collectionId: data.collection_id } });
  };
  return (
    <div className="space-y-3">
      <form onSubmit={(e) => void preview(e)} className="flex max-w-xl gap-2">
        <Input name="url" type="url" required placeholder="https://leagueofcomicgeeks.com/events/…" aria-label={t("importPage.locgUrl")} />
        <Button type="submit" variant="outline">{t("importPage.locgFind")}</Button>
      </form>
      {found && (
        <div className="flex items-center gap-3 rounded-lg border p-3 text-sm">
          <span className="flex-1 font-medium">{found.name}</span>
          <Button size="sm" onClick={() => void link()}>{t("importPage.cblLink")}</Button>
        </div>
      )}
    </div>
  );
}
