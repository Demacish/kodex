import { useNavigate } from "@tanstack/react-router";
import { Search } from "lucide-react";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { errorMessage, fetchClient, type Schemas } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

/** Finds a reading list in the CBL library and makes a story arc collection of it. */
export function CblLink() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [results, setResults] = useState<Schemas["CblSearchResult"][] | null>(null);
  const [busy, setBusy] = useState(false);
  const search = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const q = String(new FormData(event.currentTarget).get("q") ?? "").trim();
    if (!q) return;
    setBusy(true);
    const { data, error } = await fetchClient.GET("/api/cbl/search", { params: { query: { q } } });
    setBusy(false);
    if (error) return void toast.error(errorMessage(error, t("common.errorGeneric")));
    setResults(data ?? []);
  };
  const link = async (result: Schemas["CblSearchResult"]) => {
    const { data, error } = await fetchClient.POST("/api/cbl/link", { body: { path: result.path, name: result.name } });
    if (error || !data) return void toast.error(errorMessage(error, t("common.errorGeneric")));
    toast.success(t("importPage.cblLinked", { name: result.name }));
    if (data.collection_id != null) await navigate({ to: "/collections/$collectionId", params: { collectionId: data.collection_id } });
  };
  return (
    <div className="space-y-3">
      <form role="search" onSubmit={(e) => void search(e)} className="flex max-w-md gap-2">
        <Input name="q" placeholder={t("importPage.cblPlaceholder")} aria-label={t("importPage.cblPlaceholder")} />
        <Button type="submit" variant="outline" disabled={busy}><Search aria-hidden />{t("common.search")}</Button>
      </form>
      {results && results.length === 0 && <p className="text-sm text-muted-foreground">{t("searchPage.none", { q: "" })}</p>}
      {results && results.length > 0 && (
        <ul className="divide-y rounded-lg border">
          {results.map((result) => (
            <li key={result.path} className="flex items-center gap-3 px-3 py-2 text-sm">
              <span className="min-w-0 flex-1">
                <span className="block truncate font-medium">{result.name}</span>
                <span className="block truncate text-xs text-muted-foreground">{result.publisher}</span>
              </span>
              <Button size="sm" variant="outline" onClick={() => void link(result)}>{t("importPage.cblLink")}</Button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
