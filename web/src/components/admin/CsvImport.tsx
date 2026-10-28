import { useNavigate } from "@tanstack/react-router";
import { FileUp } from "lucide-react";
import { useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { csrfToken, fetchClient, type Schemas } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

type Preview = Schemas["CsvImportPreviewOut"];
type Row = Schemas["CsvImportRowOut"];
const BUCKETS = ["matched", "needs_review", "unmatched"] as const;

/** A pull list or reading list as CSV, matched against the library, becomes a collection. */
export function CsvImport() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const input = useRef<HTMLInputElement>(null);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [name, setName] = useState("");
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [busy, setBusy] = useState(false);

  const read = async (file: File) => {
    setBusy(true);
    const body = new FormData();
    body.append("file", file);
    const response = await fetch("/api/collections/import-csv/preview", { method: "POST", body, credentials: "same-origin", headers: { "X-CSRF-Token": csrfToken() ?? "" } });
    setBusy(false);
    if (!response.ok) return void toast.error(t("importPage.csvUnreadable"));
    const result = (await response.json()) as Preview;
    setPreview(result);
    setSelected(new Set((result.matched as Row[]).map((row) => row.row_index)));
    setName(file.name.replace(/\.csv$/i, ""));
  };
  const confirm = async () => {
    if (!preview) return;
    const rows = BUCKETS.flatMap((bucket) => preview[bucket] as Row[]);
    const ids = [...new Set(rows.filter((row) => selected.has(row.row_index)).flatMap((row) => row.book_ids))];
    if (ids.length === 0) return void toast.error(t("importPage.nothingChosen"));
    setBusy(true);
    const { data, error } = await fetchClient.POST("/api/collections/import-csv/confirm", { body: { name: name.trim(), book_ids: ids } });
    setBusy(false);
    if (error || !data) return void toast.error(t("common.errorGeneric"));
    await navigate({ to: "/collections/$collectionId", params: { collectionId: data.id } });
  };

  if (!preview) {
    return (
      <div>
        <input ref={input} type="file" accept=".csv,text/csv" hidden onChange={(e) => e.target.files?.[0] && void read(e.target.files[0])} />
        <Button onClick={() => input.current?.click()} disabled={busy}>
          <FileUp aria-hidden />
          {busy ? t("common.loading") : t("importPage.chooseCsv")}
        </Button>
      </div>
    );
  }
  return (
    <div className="space-y-5">
      <div className="max-w-sm space-y-1.5">
        <Label htmlFor="csv-name">{t("collections.name")}</Label>
        <Input id="csv-name" value={name} onChange={(e) => setName(e.target.value)} />
      </div>
      {BUCKETS.map((bucket) => {
        const rows = preview[bucket] as Row[];
        if (rows.length === 0) return null;
        return (
          <section key={bucket} aria-labelledby={`csv-${bucket}`}>
            <h3 id={`csv-${bucket}`} className="mb-2 text-sm font-semibold">{t(`importPage.buckets.${bucket}`, { count: rows.length })}</h3>
            <ul className="divide-y rounded-lg border">
              {rows.map((row) => (
                <li key={row.row_index} className="flex items-center gap-3 px-3 py-2 text-sm">
                  <Checkbox
                    checked={selected.has(row.row_index)}
                    disabled={row.book_ids.length === 0}
                    onCheckedChange={(on) => setSelected((current) => { const next = new Set(current); if (on) next.add(row.row_index); else next.delete(row.row_index); return next; })}
                    aria-label={row.raw_title}
                  />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate">{row.raw_title}{row.raw_issue_number && ` #${row.raw_issue_number}`}</span>
                    <span className="block truncate text-xs text-muted-foreground">
                      {row.matched_series_title ? t("importPage.matchedTo", { title: row.matched_series_title, count: row.book_ids.length }) : t("importPage.noMatch")}
                    </span>
                  </span>
                  <span className="text-xs text-muted-foreground tabular-nums">{Math.round(row.score * 100)} %</span>
                </li>
              ))}
            </ul>
          </section>
        );
      })}
      <div className="flex gap-2">
        <Button onClick={() => void confirm()} disabled={busy || !name.trim()}>{t("importPage.createCollection")}</Button>
        <Button variant="ghost" onClick={() => setPreview(null)}>{t("common.cancel")}</Button>
      </div>
    </div>
  );
}
