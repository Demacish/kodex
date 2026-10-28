import { useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { useState, type FormEvent, type ReactElement } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { api, errorMessage, type Schemas } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";

const FIELDS = ["genres", "tags", "authors", "story_arcs", "library_id", "series_id", "file_format"] as const;

type Collection = Schemas["CollectionOut"];

/** Creates a collection, or renames one and changes a smart collection's rule. */
export function CollectionDialog({ trigger, collection }: { trigger: ReactElement; collection?: Collection }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const [kind, setKind] = useState<"manual" | "smart">((collection?.collection_type as "manual" | "smart") ?? "manual");
  const [field, setField] = useState<string>("genres");
  const [negate, setNegate] = useState(false);
  const [personal, setPersonal] = useState(false);
  const create = api.useMutation("post", "/api/collections");
  const update = api.useMutation("put", "/api/collections/{collection_id}");

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const name = String(form.get("name") ?? "").trim();
    let rule: Record<string, unknown> | null = null;
    if (kind === "smart") {
      const raw = String(form.get("rule_json") ?? "").trim();
      try {
        rule = raw ? JSON.parse(raw) : { field, op: negate ? "neq" : "eq", value: field.endsWith("_id") ? Number(form.get("value")) : String(form.get("value") ?? "").trim() };
      } catch {
        toast.error(t("collections.badRule"));
        return;
      }
    }
    try {
      if (collection) {
        await update.mutateAsync({ params: { path: { collection_id: collection.id } }, body: { name, ...(kind === "smart" && rule ? { rule } : {}) } });
        toast.success(t("common.saved"));
      } else {
        const created = await create.mutateAsync({ body: { name, collection_type: kind, rule, personal, book_ids: [] } });
        await navigate({ to: "/collections/$collectionId", params: { collectionId: created.id } });
      }
      setOpen(false);
      await queryClient.invalidateQueries({ queryKey: ["get", "/api/collections"] });
      await queryClient.invalidateQueries({ queryKey: ["get", "/api/collections/{collection_id}"] });
    } catch (error) {
      toast.error(errorMessage(error, t("common.errorGeneric")));
    }
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger render={trigger} />
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{collection ? t("collections.edit") : t("collections.new")}</DialogTitle>
        </DialogHeader>
        <form onSubmit={submit} className="grid gap-4">
          <div className="space-y-1.5">
            <Label htmlFor="collection-name">{t("collections.name")}</Label>
            <Input id="collection-name" name="name" defaultValue={collection?.name} required autoFocus />
          </div>
          {!collection && (
            <>
              <ToggleGroup value={[kind]} onValueChange={(v: string[]) => v[0] && setKind(v[0] as "manual" | "smart")} variant="outline" size="sm">
                <ToggleGroupItem value="manual">{t("collections.types.manual")}</ToggleGroupItem>
                <ToggleGroupItem value="smart">{t("collections.types.smart")}</ToggleGroupItem>
              </ToggleGroup>
              <p className="text-xs text-muted-foreground">{kind === "manual" ? t("collections.manualHint") : t("collections.smartHint")}</p>
              <label className="flex items-center justify-between gap-3 text-sm">
                {t("collections.personalHint")}
                <Switch checked={personal} onCheckedChange={setPersonal} />
              </label>
            </>
          )}
          {kind === "smart" && (
            <div className="space-y-3 rounded-lg border p-3">
              {!collection && (
                <div className="flex flex-wrap gap-2">
                  <Select value={field} onValueChange={(v) => setField(String(v))}>
                    <SelectTrigger className="w-40" aria-label={t("collections.field")}>
                      <SelectValue>{(v: string) => t(`collections.fields.${v as "genres"}`)}</SelectValue>
                    </SelectTrigger>
                    <SelectContent>
                      {FIELDS.map((f) => <SelectItem key={f} value={f}>{t(`collections.fields.${f}`)}</SelectItem>)}
                    </SelectContent>
                  </Select>
                  <Select value={negate ? "neq" : "eq"} onValueChange={(v) => setNegate(v === "neq")}>
                    <SelectTrigger className="w-32" aria-label={t("collections.operator")}>
                      <SelectValue>{(v: string) => t(`collections.ops.${v as "eq"}`)}</SelectValue>
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="eq">{t("collections.ops.eq")}</SelectItem>
                      <SelectItem value="neq">{t("collections.ops.neq")}</SelectItem>
                    </SelectContent>
                  </Select>
                  <Input name="value" className="min-w-40 flex-1" aria-label={t("collections.value")} placeholder={t("collections.valueHint")} />
                </div>
              )}
              <div className="space-y-1.5">
                <Label htmlFor="rule-json">{collection ? t("collections.rule") : t("collections.advancedRule")}</Label>
                <Textarea id="rule-json" name="rule_json" rows={4} className="font-mono text-xs" defaultValue={collection?.rule ? JSON.stringify(collection.rule, null, 2) : ""}
                  placeholder='{"all": [{"field": "genres", "value": "Fantasy"}, {"field": "library_id", "value": 1}]}' />
              </div>
            </div>
          )}
          <DialogFooter>
            <Button type="button" variant="ghost" onClick={() => setOpen(false)}>{t("common.cancel")}</Button>
            <Button type="submit" disabled={create.isPending || update.isPending}>{collection ? t("common.save") : t("common.create")}</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

/** Asks the AI for a collection from a description. */
export function GenerateCollectionDialog({ trigger }: { trigger: ReactElement }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const generate = api.useMutation("post", "/api/collections/generate");
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    try {
      const created = await generate.mutateAsync({ body: { prompt: String(form.get("prompt") ?? ""), name: String(form.get("name") ?? "") || null } });
      setOpen(false);
      await queryClient.invalidateQueries({ queryKey: ["get", "/api/collections"] });
      await navigate({ to: "/collections/$collectionId", params: { collectionId: created.id } });
    } catch (error) {
      toast.error(errorMessage(error, t("discover.failed")));
    }
  };
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger render={trigger} />
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{t("collections.generate")}</DialogTitle>
        </DialogHeader>
        <form onSubmit={submit} className="grid gap-4">
          <div className="space-y-1.5">
            <Label htmlFor="generate-prompt">{t("collections.prompt")}</Label>
            <Textarea id="generate-prompt" name="prompt" rows={3} required placeholder={t("collections.promptHint")} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="generate-name">{t("collections.nameOptional")}</Label>
            <Input id="generate-name" name="name" />
          </div>
          <DialogFooter>
            <Button type="button" variant="ghost" onClick={() => setOpen(false)}>{t("common.cancel")}</Button>
            <Button type="submit" disabled={generate.isPending}>{generate.isPending ? t("common.loading") : t("common.create")}</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

/** Builds a story arc collection from its Comic Vine id. */
export function StoryArcImportDialog({ trigger }: { trigger: ReactElement }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const build = api.useMutation("post", "/api/collections/story-arc-import");
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    try {
      const result = await build.mutateAsync({ body: { comicvine_story_arc_id: Number(form.get("id")), name: String(form.get("name") ?? "") || null } });
      setOpen(false);
      toast.success(t("collections.arcQueued"));
      await navigate({ to: "/collections/$collectionId", params: { collectionId: result.collection_id } });
    } catch (error) {
      toast.error(errorMessage(error, t("common.errorGeneric")));
    }
  };
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger render={trigger} />
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{t("collections.fromArc")}</DialogTitle>
        </DialogHeader>
        <form onSubmit={submit} className="grid gap-4">
          <p className="text-sm text-muted-foreground">{t("collections.fromArcHint")}</p>
          <div className="space-y-1.5">
            <Label htmlFor="arc-id">{t("collections.arcId")}</Label>
            <Input id="arc-id" name="id" type="number" min={1} required />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="arc-name">{t("collections.nameOptional")}</Label>
            <Input id="arc-name" name="name" />
          </div>
          <DialogFooter>
            <Button type="button" variant="ghost" onClick={() => setOpen(false)}>{t("common.cancel")}</Button>
            <Button type="submit" disabled={build.isPending}>{t("common.create")}</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
