import { useQueryClient } from "@tanstack/react-query";
import { createFileRoute, Link } from "@tanstack/react-router";
import { Download, Inbox, Layers, Send } from "lucide-react";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { api, errorMessage, type Schemas } from "@/api/client";
import { EmptyState, ErrorState, PageHeader } from "@/components/common/states";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { format } from "@/i18n";
import { useAccount } from "@/lib/account";
import { oneOf, searchSchema } from "@/lib/search";

type Request = Schemas["RequestOut"];
const STATUSES = ["pending", "approved", "fulfilled", "rejected"] as const;
const MEDIA = ["series", "ebook", "manga"] as const;
const VARIANT = { pending: "secondary", approved: "default", fulfilled: "outline", rejected: "destructive" } as const;
const search = searchSchema(
  { view: "mine" as "mine" | "all", status: "all" as "all" | (typeof STATUSES)[number] },
  { view: oneOf(["mine", "all"] as const), status: oneOf(["all", ...STATUSES] as const) },
);

export const Route = createFileRoute("/_authed/_shell/requests")({
  validateSearch: search.validate,
  component: Requests,
});

function Requests() {
  const { t } = useTranslation();
  const account = useAccount();
  const state = search.resolve(Route.useSearch());
  const navigate = Route.useNavigate();
  const view = account.is_admin ? state.view : "mine";
  return (
    <div className="max-w-3xl">
      <PageHeader title={t("nav.requests")} description={t("requests.intro")} />
      {account.role !== "guest" && <NewRequest />}
      {account.is_admin && (
        <Tabs value={view} onValueChange={(v) => navigate({ search: search.update({ view: v as "mine" | "all" }) })} className="mb-4">
          <TabsList>
            <TabsTrigger value="mine">{t("requests.mine")}</TabsTrigger>
            <TabsTrigger value="all">{t("requests.all")}</TabsTrigger>
          </TabsList>
        </Tabs>
      )}
      {view === "mine" ? <Mine /> : <All status={state.status} onStatus={(status) => navigate({ search: search.update({ status }) })} />}
    </div>
  );
}

function NewRequest() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [media, setMedia] = useState<(typeof MEDIA)[number]>("series");
  const create = api.useMutation("post", "/api/requests");
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    try {
      await create.mutateAsync({ body: { title: String(data.get("title") ?? "").trim(), media_type: media, external_link: String(data.get("link") ?? "").trim() || null } });
      toast.success(t("requests.sent"));
      form.reset();
      await queryClient.invalidateQueries({ queryKey: ["get", "/api/requests/mine"] });
      await queryClient.invalidateQueries({ queryKey: ["get", "/api/requests"] });
    } catch (error) {
      toast.error(errorMessage(error, t("requests.invalid")));
    }
  };
  return (
    <section aria-labelledby="new-request" className="mb-8 rounded-xl border bg-card p-5">
      <h2 id="new-request" className="mb-1 font-semibold">{t("requests.newTitle")}</h2>
      <p className="mb-4 text-sm text-muted-foreground">{t("requests.newIntro")}</p>
      <form onSubmit={submit} className="grid gap-3">
        <div className="space-y-1.5">
          <Label htmlFor="request-title">{t("list.title")}</Label>
          <Input id="request-title" name="title" required />
        </div>
        <div className="flex flex-wrap gap-3">
          <div className="space-y-1.5">
            <Label>{t("requests.type")}</Label>
            <Select value={media} onValueChange={(v) => setMedia(v as (typeof MEDIA)[number])}>
              <SelectTrigger className="w-36" aria-label={t("requests.type")}>
                <SelectValue>{(v: string) => t(`requests.media.${v as "series"}`)}</SelectValue>
              </SelectTrigger>
              <SelectContent>
                {MEDIA.map((m) => <SelectItem key={m} value={m}>{t(`requests.media.${m}`)}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>
          <div className="min-w-60 flex-1 space-y-1.5">
            <Label htmlFor="request-link">{t("requests.link")}</Label>
            <Input id="request-link" name="link" type="url" placeholder="https://" />
          </div>
        </div>
        <div>
          <Button type="submit" disabled={create.isPending}>
            <Send aria-hidden />
            {t("requests.send")}
          </Button>
        </div>
      </form>
    </section>
  );
}

function Status({ request }: { request: Request }) {
  const { t } = useTranslation();
  return <Badge variant={VARIANT[request.status]}>{t(`requests.status.${request.status}`)}</Badge>;
}

function Mine() {
  const { t } = useTranslation();
  const mine = api.useQuery("get", "/api/requests/mine");
  if (mine.isError) return <ErrorState error={mine.error} onRetry={() => void mine.refetch()} />;
  if (mine.isPending) return <Skeleton className="h-32 rounded-xl" />;
  if (mine.data.length === 0) return <EmptyState icon={Inbox} title={t("requests.noneMine")} />;
  return (
    <ul className="divide-y rounded-xl border bg-card">
      {mine.data.map((request) => (
        <li key={request.id} className="flex items-center gap-3 px-4 py-3">
          <div className="min-w-0 flex-1">
            <div className="truncate font-medium">{request.title}</div>
            <div className="truncate text-xs text-muted-foreground">
              {t(`requests.media.${request.media_type}`)} · {format.date(request.created_at)}
              {request.admin_note && ` · ${request.admin_note}`}
            </div>
          </div>
          <Status request={request} />
        </li>
      ))}
    </ul>
  );
}

function All({ status, onStatus }: { status: "all" | (typeof STATUSES)[number]; onStatus: (status: "all" | (typeof STATUSES)[number]) => void }) {
  const { t } = useTranslation();
  const all = api.useQuery("get", "/api/requests", { params: { query: status === "all" ? {} : { status } } });
  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <ToggleGroup value={[status]} onValueChange={(v: string[]) => v[0] && onStatus(v[0] as typeof status)} variant="outline" size="sm" className="flex-wrap">
          <ToggleGroupItem value="all">{t("list.status.all")}</ToggleGroupItem>
          {STATUSES.map((s) => <ToggleGroupItem key={s} value={s}>{t(`requests.status.${s}`)}</ToggleGroupItem>)}
        </ToggleGroup>
        <Button variant="outline" size="sm" render={<a href={`/api/requests/export${status === "all" ? "" : `?status=${status}`}`} download />}>
          <Download aria-hidden />
          {t("requests.export")}
        </Button>
      </div>
      {all.isError ? (
        <ErrorState error={all.error} onRetry={() => void all.refetch()} />
      ) : all.isPending ? (
        <Skeleton className="h-32 rounded-xl" />
      ) : all.data.length === 0 ? (
        <EmptyState icon={Inbox} title={t("requests.none")} />
      ) : (
        <ul className="space-y-3">
          {all.data.map((request) => <AdminRequest key={request.id} request={request} />)}
        </ul>
      )}
    </div>
  );
}

function AdminRequest({ request }: { request: Request }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [status, setStatus] = useState<string>(request.status);
  const update = api.useMutation("put", "/api/requests/{request_id}");
  const save = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const note = String(new FormData(event.currentTarget).get("note") ?? "");
    try {
      await update.mutateAsync({ params: { path: { request_id: request.id } }, body: { status: status as Request["status"], admin_note: note || null } });
      toast.success(t("common.saved"));
      await queryClient.invalidateQueries({ queryKey: ["get", "/api/requests"] });
    } catch (error) {
      toast.error(errorMessage(error, t("common.errorGeneric")));
    }
  };
  return (
    <li className="rounded-xl border bg-card p-4">
      <div className="mb-1 flex flex-wrap items-center justify-between gap-2">
        <span className="font-medium">{request.title}</span>
        <span className="flex items-center gap-2 text-xs text-muted-foreground">
          {t(`requests.media.${request.media_type}`)}
          <Status request={request} />
        </span>
      </div>
      <div className="mb-3 flex flex-wrap items-center gap-x-2 text-xs text-muted-foreground">
        {t("requests.by", { name: request.requested_by_username, when: format.date(request.created_at) })}
        {request.collection_id && request.collection_name && (
          <Link to="/collections/$collectionId" params={{ collectionId: request.collection_id }} className="inline-flex items-center gap-1 text-primary-text hover:underline">
            <Layers className="size-3" aria-hidden />
            {request.collection_name}
          </Link>
        )}
        {request.external_link && (
          <a href={request.external_link} target="_blank" rel="noreferrer noopener" className="text-primary-text hover:underline">{t("requests.linkShort")}</a>
        )}
      </div>
      <form onSubmit={save} className="flex flex-wrap items-center gap-2">
        <Select value={status} onValueChange={(v) => setStatus(String(v))}>
          <SelectTrigger size="sm" className="w-32" aria-label={t("requests.statusLabel")}>
            <SelectValue>{(v: string) => t(`requests.status.${v as "pending"}`)}</SelectValue>
          </SelectTrigger>
          <SelectContent>
            {STATUSES.map((s) => <SelectItem key={s} value={s}>{t(`requests.status.${s}`)}</SelectItem>)}
          </SelectContent>
        </Select>
        <Input name="note" defaultValue={request.admin_note ?? ""} placeholder={t("requests.note")} aria-label={t("requests.note")} className="h-7 min-w-40 flex-1 text-sm" />
        <Button type="submit" size="sm" disabled={update.isPending}>{t("common.save")}</Button>
      </form>
    </li>
  );
}
