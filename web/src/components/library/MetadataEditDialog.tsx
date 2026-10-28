import { useQueryClient } from "@tanstack/react-query";
import { Pencil } from "lucide-react";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { api, errorMessage, type Schemas } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";

const list = (value: FormDataEntryValue | null) =>
  String(value ?? "").split(",").map((part) => part.trim()).filter(Boolean);

/** An admin's hand-typed correction of a book's metadata. */
export function MetadataEditDialog({ book }: { book: Schemas["BookOut"] }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [edition, setEdition] = useState<string>(book.edition_type);
  const save = api.useMutation("patch", "/api/books/{book_id}");
  const meta = book.book_metadata;
  if (!meta) return null;

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const year = String(form.get("published_year") ?? "").trim();
    try {
      await save.mutateAsync({
        params: { path: { book_id: book.id } },
        body: {
          title: String(form.get("title") ?? "").trim(),
          sort_title: String(form.get("sort_title") ?? "").trim() || null,
          authors: list(form.get("authors")),
          genres: list(form.get("genres")),
          tags: list(form.get("tags")),
          summary: String(form.get("summary") ?? "").trim() || null,
          publisher: String(form.get("publisher") ?? "").trim() || null,
          published_year: year ? Number(year) : null,
          language: String(form.get("language") ?? "").trim() || null,
          edition_type: edition as Schemas["BookEditionType"],
        },
      });
      toast.success(t("common.saved"));
      setOpen(false);
      await queryClient.invalidateQueries({ queryKey: ["get", "/api/books/{book_id}"] });
      await queryClient.invalidateQueries({ queryKey: ["get", "/api/books"] });
    } catch (error) {
      toast.error(errorMessage(error, t("common.errorGeneric")));
    }
  };

  const field = (name: string, label: string, value: string | number | null | undefined, props: Record<string, unknown> = {}) => (
    <div className="space-y-1.5">
      <Label htmlFor={`meta-${name}`}>{label}</Label>
      <Input id={`meta-${name}`} name={name} defaultValue={value ?? ""} {...props} />
    </div>
  );

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger render={<Button variant="outline" size="sm" />}>
        <Pencil aria-hidden />
        {t("common.edit")}
      </DialogTrigger>
      <DialogContent className="max-h-[90dvh] overflow-y-auto sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>{t("book.editMetadata")}</DialogTitle>
        </DialogHeader>
        <form onSubmit={submit} className="grid gap-4">
          {field("title", t("list.title"), meta.title, { required: true })}
          {field("sort_title", t("book.sortTitle"), meta.sort_title)}
          {field("authors", t("book.authors"), meta.authors.join(", "))}
          <div className="grid gap-4 sm:grid-cols-3">
            {field("publisher", t("book.publisher"), meta.publisher)}
            {field("published_year", t("book.year"), meta.published_year, { type: "number", min: 0, max: 3000 })}
            {field("language", t("book.language"), meta.language)}
          </div>
          {field("genres", t("book.genres"), meta.genres.join(", "))}
          {field("tags", t("book.tags"), meta.tags.join(", "))}
          <div className="space-y-1.5">
            <Label>{t("book.edition")}</Label>
            <Select value={edition} onValueChange={(value) => setEdition(String(value))}>
              <SelectTrigger className="w-full" aria-label={t("book.edition")}>
                <SelectValue>{(value: string) => t(`book.editions.${value as "issue"}`)}</SelectValue>
              </SelectTrigger>
              <SelectContent>
                {["issue", "collected"].map((value) => (
                  <SelectItem key={value} value={value}>{t(`book.editions.${value as "issue"}`)}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="meta-summary">{t("book.summary")}</Label>
            <Textarea id="meta-summary" name="summary" defaultValue={meta.summary ?? ""} rows={5} />
          </div>
          <p className="text-xs text-muted-foreground">{t("book.listHint")}</p>
          <DialogFooter>
            <Button type="button" variant="ghost" onClick={() => setOpen(false)}>{t("common.cancel")}</Button>
            <Button type="submit" disabled={save.isPending}>{t("common.save")}</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
