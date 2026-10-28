import { useQueryClient } from "@tanstack/react-query";
import { createFileRoute, Link } from "@tanstack/react-router";
import { FolderSearch, Plus, RefreshCw, Settings2, Upload } from "lucide-react";
import { useRef, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { api, csrfToken, errorMessage, fetchClient, type Schemas } from "@/api/client";
import { EmptyState, ErrorState, PageHeader } from "@/components/common/states";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Progress } from "@/components/ui/progress";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { format } from "@/i18n";

type Library = Schemas["LibraryOut"];
const TYPES = ["comics", "manga", "ebooks", "mixed"] as const;

export const Route = createFileRoute("/_authed/_shell/admin/libraries")({
  component: AdminLibraries,
});

function AdminLibraries() {
  const { t } = useTranslation();
  const libraries = api.useQuery("get", "/api/libraries");
  return (
    <div>
      <PageHeader title={t("admin.nav.libraries")} description={t("adminLibraries.intro")} actions={<LibraryDialog />} />
      {libraries.isError ? (
        <ErrorState error={libraries.error} onRetry={() => void libraries.refetch()} />
      ) : libraries.isPending ? (
        <Skeleton className="h-40 rounded-xl" />
      ) : libraries.data.length === 0 ? (
        <EmptyState title={t("home.noLibraries")}>{t("adminLibraries.createFirst")}</EmptyState>
      ) : (
        <ul className="space-y-4">
          {libraries.data.map((library) => <LibraryRow key={library.id} library={library} />)}
        </ul>
      )}
    </div>
  );
}

function useJob() {
  const { t } = useTranslation();
  return async (call: () => Promise<{ error?: unknown }>, done: string) => {
    const { error } = await call();
    if (error) toast.error(errorMessage(error, t("common.errorGeneric")));
    else toast.success(done, { action: { label: t("adminLibraries.seeJobs"), onClick: () => window.location.assign("/admin/jobs") } });
  };
}

function LibraryRow({ library }: { library: Library }) {
  const { t } = useTranslation();
  const job = useJob();
  const path = { params: { path: { library_id: library.id } } };
  return (
    <li className="rounded-xl border bg-card p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <Link to="/libraries/$libraryId" params={{ libraryId: library.id }} className="font-semibold hover:text-primary-text">{library.name}</Link>
            <Badge variant="secondary">{t(`adminLibraries.types.${library.library_type as "comics"}`)}</Badge>
            {library.read_only && <Badge variant="outline">{t("adminLibraries.readOnly")}</Badge>}
            {library.write_back && <Badge variant="outline">{t("adminLibraries.writeBack")}</Badge>}
          </div>
          <p className="mt-1 text-xs text-muted-foreground">
            <code className="rounded bg-muted px-1">{library.path}</code> ·{" "}
            {library.last_scanned_at ? t("adminLibraries.scanned", { when: format.relative(library.last_scanned_at) }) : t("adminLibraries.neverScanned")} ·{" "}
            {library.last_fulltext_indexed_at ? t("adminLibraries.indexed", { when: format.relative(library.last_fulltext_indexed_at) }) : t("adminLibraries.notIndexed")}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button size="sm" onClick={() => void job(() => fetchClient.POST("/api/libraries/{library_id}/scan", path), t("adminLibraries.scanQueued"))}>
            <RefreshCw aria-hidden />
            {t("adminLibraries.scan")}
          </Button>
          <Button size="sm" variant="outline" onClick={() => void job(() => fetchClient.POST("/api/matching/libraries/{library_id}/match", path), t("adminLibraries.matchQueued"))}>
            <FolderSearch aria-hidden />
            {t("adminLibraries.match")}
          </Button>
          {!library.read_only && <UploadDialog library={library} />}
          <DropdownMenu>
            <DropdownMenuTrigger render={<Button size="sm" variant="ghost" aria-label={t("common.more")} />}>
              <Settings2 aria-hidden />
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-60">
              <DropdownMenuGroup>
                <DropdownMenuItem onClick={() => void job(() => fetchClient.POST("/api/matching/libraries/{library_id}/match", { params: { path: { library_id: library.id }, query: { force: true } } }), t("adminLibraries.matchQueued"))}>
                  {t("adminLibraries.matchAll")}
                </DropdownMenuItem>
                <DropdownMenuItem onClick={() => void job(() => fetchClient.POST("/api/libraries/{library_id}/enrich", path), t("adminLibraries.enrichQueued"))}>
                  {t("adminLibraries.enrich")}
                </DropdownMenuItem>
                <DropdownMenuItem onClick={() => void job(() => fetchClient.POST("/api/libraries/{library_id}/fulltext-index", path), t("adminLibraries.indexQueued"))}>
                  {t("adminLibraries.fulltext")}
                </DropdownMenuItem>
                <DropdownMenuItem onClick={() => void job(() => fetchClient.POST("/api/libraries/{library_id}/detect-panels", path), t("adminLibraries.panelsQueued"))}>
                  {t("adminLibraries.panels")}
                </DropdownMenuItem>
                <DropdownMenuItem onClick={() => void job(() => fetchClient.POST("/api/libraries/{library_id}/import-series-json", path), t("adminLibraries.seriesJsonImported"))}>
                  {t("adminLibraries.seriesJson")}
                </DropdownMenuItem>
                {library.write_back && !library.read_only && (
                  <DropdownMenuItem onClick={() => void job(() => fetchClient.POST("/api/library/libraries/{library_id}/write-back", path), t("adminLibraries.writeBackQueued"))}>
                    {t("adminLibraries.writeBackNow")}
                  </DropdownMenuItem>
                )}
              </DropdownMenuGroup>
              <DropdownMenuSeparator />
              <LibraryDialog library={library} asMenuItem />
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </div>
    </li>
  );
}

function LibraryDialog({ library, asMenuItem = false }: { library?: Library; asMenuItem?: boolean }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [type, setType] = useState<string>(library?.library_type ?? "comics");
  const [readOnly, setReadOnly] = useState(library?.read_only ?? false);
  const [writeBack, setWriteBack] = useState(library?.write_back ?? false);
  const create = api.useMutation("post", "/api/libraries");
  const update = api.useMutation("patch", "/api/libraries/{library_id}");
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    try {
      if (library) {
        await update.mutateAsync({ params: { path: { library_id: library.id } }, body: { name: String(form.get("name")), library_type: type as Library["library_type"], read_only: readOnly, write_back: writeBack } });
      } else {
        await create.mutateAsync({ body: { name: String(form.get("name")), path: String(form.get("path")), library_type: type as Library["library_type"] } });
      }
      toast.success(t("common.saved"));
      setOpen(false);
      await queryClient.invalidateQueries({ queryKey: ["get", "/api/libraries"] });
    } catch (error) {
      toast.error(errorMessage(error, t("adminLibraries.invalid")));
    }
  };
  const trigger = asMenuItem ? <DropdownMenuItem closeOnClick={false} /> : <Button size="sm" />;
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger render={trigger}>
        {library ? <Settings2 aria-hidden /> : <Plus aria-hidden />}
        {library ? t("adminLibraries.settings") : t("adminLibraries.new")}
      </DialogTrigger>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{library ? t("adminLibraries.settingsFor", { name: library.name }) : t("adminLibraries.new")}</DialogTitle>
        </DialogHeader>
        <form onSubmit={submit} className="grid gap-4">
          <div className="space-y-1.5">
            <Label htmlFor="lib-name">{t("collections.name")}</Label>
            <Input id="lib-name" name="name" defaultValue={library?.name} required placeholder={t("adminLibraries.namePlaceholder")} />
          </div>
          {!library && (
            <div className="space-y-1.5">
              <Label htmlFor="lib-path">{t("adminLibraries.path")}</Label>
              <Input id="lib-path" name="path" required placeholder={t("adminLibraries.pathPlaceholder")} />
              <p className="text-xs text-muted-foreground">{t("adminLibraries.pathHint")}</p>
            </div>
          )}
          <div className="space-y-1.5">
            <Label>{t("requests.type")}</Label>
            <Select value={type} onValueChange={(v) => setType(String(v))}>
              <SelectTrigger className="w-full" aria-label={t("requests.type")}>
                <SelectValue>{(v: string) => t(`adminLibraries.types.${v as "comics"}`)}</SelectValue>
              </SelectTrigger>
              <SelectContent>
                {TYPES.map((value) => <SelectItem key={value} value={value}>{t(`adminLibraries.types.${value}`)}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>
          {library && (
            <>
              <label className="flex items-start justify-between gap-4">
                <span><span className="block text-sm font-medium">{t("adminLibraries.readOnly")}</span><span className="block text-xs text-muted-foreground">{t("adminLibraries.readOnlyHint")}</span></span>
                <Switch checked={readOnly} onCheckedChange={setReadOnly} />
              </label>
              <label className="flex items-start justify-between gap-4">
                <span><span className="block text-sm font-medium">{t("adminLibraries.writeBack")}</span><span className="block text-xs text-muted-foreground">{t("adminLibraries.writeBackHint")}</span></span>
                <Switch checked={writeBack} onCheckedChange={setWriteBack} disabled={readOnly} />
              </label>
            </>
          )}
          <DialogFooter>
            <Button type="button" variant="ghost" onClick={() => setOpen(false)}>{t("common.cancel")}</Button>
            <Button type="submit" disabled={create.isPending || update.isPending}>{library ? t("common.save") : t("common.create")}</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function UploadDialog({ library }: { library: Library }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [files, setFiles] = useState<File[]>([]);
  const [done, setDone] = useState(0);
  const [busy, setBusy] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const subfolder = useRef<HTMLInputElement>(null);
  const upload = async () => {
    setBusy(true);
    setDone(0);
    let failed = 0;
    for (const [i, file] of files.entries()) {
      const body = new FormData();
      body.append("file", file);
      body.append("subfolder", subfolder.current?.value ?? "");
      body.append("rescan", String(i === files.length - 1));
      const response = await fetch(`/api/libraries/${library.id}/upload`, { method: "POST", body, credentials: "same-origin", headers: { "X-CSRF-Token": csrfToken() ?? "" } });
      if (!response.ok) failed += 1;
      setDone(i + 1);
    }
    setBusy(false);
    if (failed) toast.error(t("adminLibraries.uploadFailed", { count: failed }));
    else toast.success(t("adminLibraries.uploaded", { count: files.length }));
    setFiles([]);
    setOpen(false);
  };
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger render={<Button size="sm" variant="outline" />}>
        <Upload aria-hidden />
        {t("adminLibraries.upload")}
      </DialogTrigger>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{t("adminLibraries.uploadTo", { name: library.name })}</DialogTitle>
        </DialogHeader>
        <div
          className="grid place-items-center gap-2 rounded-xl border-2 border-dashed p-8 text-center text-sm text-muted-foreground"
          onDragOver={(e) => e.preventDefault()}
          onDrop={(e) => {
            e.preventDefault();
            setFiles([...files, ...Array.from(e.dataTransfer.files)]);
          }}
        >
          <Upload className="size-6" aria-hidden />
          {t("adminLibraries.drop")}
          <Button size="sm" variant="outline" onClick={() => input.current?.click()}>{t("adminLibraries.chooseFiles")}</Button>
          <input ref={input} type="file" multiple accept=".cbz,.cbr,.cb7,.epub,.pdf,.zip,.rar,.7z" className="hidden" onChange={(e) => setFiles([...files, ...Array.from(e.target.files ?? [])])} />
        </div>
        {files.length > 0 && <p className="text-sm">{t("adminLibraries.chosen", { count: files.length })}</p>}
        <div className="space-y-1.5">
          <Label htmlFor="upload-folder">{t("adminLibraries.subfolder")}</Label>
          <Input id="upload-folder" ref={subfolder} placeholder={t("adminLibraries.subfolderPlaceholder")} />
        </div>
        {busy && <Progress value={(done / files.length) * 100} aria-label={t("adminLibraries.uploading")} />}
        <DialogFooter>
          <Button variant="ghost" onClick={() => setOpen(false)}>{t("common.cancel")}</Button>
          <Button onClick={() => void upload()} disabled={files.length === 0 || busy}>{t("adminLibraries.upload")}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
