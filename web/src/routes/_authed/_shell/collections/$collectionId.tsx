import { useQueryClient } from "@tanstack/react-query";
import { createFileRoute, Link, useNavigate } from "@tanstack/react-router";
import { ArrowDown, ArrowDownUp, ArrowUp, ChevronLeft, Download, GripVertical, ImageUp, Inbox, Pencil, RefreshCw, Trash2, X } from "lucide-react";
import { useRef, useState, type PointerEvent } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { api, errorMessage, fetchClient, csrfToken, type Schemas } from "@/api/client";
import { BookPicker } from "@/components/collections/BookPicker";
import { CollectionDialog } from "@/components/collections/CollectionDialog";
import { ConfirmDialog } from "@/components/common/ConfirmDialog";
import { ExpandableText } from "@/components/common/ExpandableText";
import { CoverGridSkeleton, EmptyState, ErrorState, PageHeader } from "@/components/common/states";
import { bookTitle } from "@/components/library/BookCard";
import { BookList } from "@/components/library/BookList";
import { Cover } from "@/components/library/Cover";
import { CoverGrid } from "@/components/library/CoverGrid";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { format } from "@/i18n";
import { useAccount } from "@/lib/account";
import { idParam } from "@/lib/params";

export const Route = createFileRoute("/_authed/_shell/collections/$collectionId")({
  params: idParam("collectionId"),
  component: CollectionPage,
});

function CollectionPage() {
  const { t } = useTranslation();
  const account = useAccount();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { collectionId } = Route.useParams();
  const path = { params: { path: { collection_id: collectionId } } };
  const collection = api.useQuery("get", "/api/collections/{collection_id}", path);
  const smart = collection.data?.collection_type === "smart";
  const arc = api.useQuery("get", "/api/collections/{collection_id}/story-arc", path, { enabled: smart, retry: false });
  const books = api.useQuery("get", "/api/collections/{collection_id}/books", path, { enabled: !!collection.data && !arc.data });
  const remove = api.useMutation("delete", "/api/collections/{collection_id}");
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ["get", "/api/collections/{collection_id}/books"] });
    void queryClient.invalidateQueries({ queryKey: ["get", "/api/collections/{collection_id}"] });
    void queryClient.invalidateQueries({ queryKey: ["get", "/api/collections"] });
  };

  if (collection.isError) return <ErrorState error={collection.error} onRetry={() => void collection.refetch()} />;
  if (!collection.data) return <CoverGridSkeleton />;
  const c = collection.data;
  const manual = c.collection_type === "manual";
  const canEdit = account.is_admin;

  const addBooks = async (ids: number[]) => {
    await fetchClient.POST("/api/collections/{collection_id}/books", { ...path, body: ids });
    toast.success(t("collections.added", { count: ids.length }));
    refresh();
  };

  return (
    <div>
      <Link to="/collections" className="mb-4 inline-flex items-center text-sm text-muted-foreground hover:text-foreground">
        <ChevronLeft className="size-4" aria-hidden />
        {t("nav.collections")}
      </Link>
      <PageHeader
        title={c.name}
        description={arc.data ? t("collections.arcIntro") : smart ? t("collections.smartIntro") : t("collections.manualIntro")}
        actions={
          <>
            <Button variant="outline" size="sm" render={<a href={`/api/collections/${c.id}/cbl`} download />}>
              <Download aria-hidden />
              {t("collections.exportCbl")}
            </Button>
            {canEdit && (
            <>
              {manual && <BookPicker onPick={addBooks} />}
              {manual && <CoverManager collection={c} onChange={refresh} />}
              <CollectionDialog collection={c} trigger={<Button variant="outline" size="sm"><Pencil aria-hidden />{t("common.edit")}</Button>} />
              <ConfirmDialog
                trigger={<Button variant="ghost" size="sm" aria-label={t("collections.delete")}><Trash2 aria-hidden /></Button>}
                title={t("collections.deleteTitle", { name: c.name })}
                description={t("collections.deleteText")}
                confirm={t("common.delete")}
                onConfirm={async () => {
                  await remove.mutateAsync(path);
                  await queryClient.invalidateQueries({ queryKey: ["get", "/api/collections"] });
                  await navigate({ to: "/collections" });
                }}
              />
            </>
            )}
          </>
        }
      />
      {arc.data?.description && <ExpandableText text={arc.data.description} className="mb-6 max-w-3xl text-sm text-muted-foreground" />}
      {arc.data ? (
        <StoryArc arc={arc.data} collectionId={c.id} admin={account.is_admin} />
      ) : books.isPending ? (
        <CoverGridSkeleton />
      ) : books.isError ? (
        <ErrorState error={books.error} onRetry={() => void books.refetch()} />
      ) : books.data.length === 0 ? (
        <EmptyState title={t("collections.empty")} />
      ) : manual && canEdit ? (
        <ManualBooks collectionId={c.id} books={books.data} onChange={refresh} />
      ) : (
        <BookList books={books.data} />
      )}
    </div>
  );
}

function ManualBooks({ collectionId, books, onChange }: { collectionId: number; books: Schemas["BookOut"][]; onChange: () => void }) {
  const { t } = useTranslation();
  const [ordering, setOrdering] = useState<Schemas["BookOut"][] | null>(null);
  const path = { params: { path: { collection_id: collectionId } } };
  const move = (index: number, to: number) =>
    setOrdering((current) => {
      if (!current || to < 0 || to >= current.length) return current;
      const next = [...current];
      const [item] = next.splice(index, 1);
      next.splice(to, 0, item!);
      return next;
    });
  // Dragging by the handle, with a mouse or a finger; the buttons do the same from the keyboard.
  const list = useRef<HTMLOListElement>(null);
  const [dragged, setDragged] = useState<number | null>(null);
  const grab = (index: number) => (event: PointerEvent<HTMLButtonElement>) => {
    event.currentTarget.setPointerCapture(event.pointerId);
    setDragged(index);
  };
  const drag = (event: PointerEvent<HTMLButtonElement>) => {
    if (dragged === null || !list.current) return;
    const rows = [...list.current.children] as HTMLElement[];
    const over = rows.findIndex((row) => {
      const box = row.getBoundingClientRect();
      return event.clientY >= box.top && event.clientY < box.bottom;
    });
    if (over >= 0 && over !== dragged) {
      move(dragged, over);
      setDragged(over);
    }
  };
  const save = async () => {
    if (!ordering) return;
    const { error } = await fetchClient.PUT("/api/collections/{collection_id}/order", { ...path, body: ordering.map((b) => b.id) });
    if (error) return void toast.error(t("common.errorGeneric"));
    toast.success(t("collections.orderSaved"));
    setOrdering(null);
    onChange();
  };

  if (ordering) {
    return (
      <div>
        <div className="mb-3 flex items-center justify-end gap-2">
          <span className="mr-auto text-sm text-muted-foreground">{t("collections.dragHint")}</span>
          <Button variant="ghost" size="sm" onClick={() => setOrdering(null)}><X aria-hidden />{t("common.cancel")}</Button>
          <Button size="sm" onClick={() => void save()}>{t("common.save")}</Button>
        </div>
        <ol ref={list} className="divide-y rounded-xl border bg-card">
          {ordering.map((book, index) => (
            <li key={book.id} className={dragged === index ? "flex items-center gap-3 bg-accent px-3 py-2" : "flex items-center gap-3 px-3 py-2"}>
              <button
                type="button"
                className="cursor-grab touch-none text-muted-foreground active:cursor-grabbing"
                aria-hidden
                tabIndex={-1}
                onPointerDown={grab(index)}
                onPointerMove={drag}
                onPointerUp={() => setDragged(null)}
                onPointerCancel={() => setDragged(null)}
              >
                <GripVertical className="size-4" />
              </button>
              <span className="w-6 text-right text-sm text-muted-foreground tabular-nums">{index + 1}</span>
              <Cover bookId={book.id} alt="" size="small" className="w-8 shrink-0" />
              <span className="min-w-0 flex-1 truncate text-sm">{bookTitle(book)}</span>
              <Button variant="ghost" size="icon-sm" disabled={index === 0} onClick={() => move(index, index - 1)} aria-label={t("collections.moveUp", { title: bookTitle(book) })}><ArrowUp aria-hidden /></Button>
              <Button variant="ghost" size="icon-sm" disabled={index === ordering.length - 1} onClick={() => move(index, index + 1)} aria-label={t("collections.moveDown", { title: bookTitle(book) })}><ArrowDown aria-hidden /></Button>
            </li>
          ))}
        </ol>
      </div>
    );
  }
  return (
    <BookList
      books={books}
      extraActions={<Button variant="outline" size="sm" onClick={() => setOrdering(books)}><ArrowDownUp aria-hidden />{t("collections.reorder")}</Button>}
      selectionActions={(ids, done) => (
        <Button
          size="sm"
          variant="destructive"
          disabled={ids.length === 0}
          onClick={async () => {
            await fetchClient.DELETE("/api/collections/{collection_id}/books", { ...path, body: ids });
            toast.success(t("collections.removed", { count: ids.length }));
            done();
            onChange();
          }}
        >
          {t("collections.removeSelected")}
        </Button>
      )}
    />
  );
}

function CoverManager({ collection, onChange }: { collection: Schemas["CollectionOut"]; onChange: () => void }) {
  const { t } = useTranslation();
  const input = useRef<HTMLInputElement>(null);
  const upload = async (file: File) => {
    const body = new FormData();
    body.append("file", file);
    const response = await fetch(`/api/collections/${collection.id}/cover`, {
      method: "POST",
      body,
      credentials: "same-origin",
      headers: { "X-CSRF-Token": csrfToken() ?? "" },
    });
    if (!response.ok) return void toast.error(t("collections.coverFailed"));
    toast.success(t("collections.coverSaved"));
    onChange();
  };
  return (
    <>
      <input ref={input} type="file" accept="image/*" className="hidden" onChange={(e) => e.target.files?.[0] && void upload(e.target.files[0])} />
      <Button variant="outline" size="sm" onClick={() => input.current?.click()}><ImageUp aria-hidden />{t("collections.cover")}</Button>
      {collection.has_custom_cover && (
        <Button
          variant="ghost"
          size="sm"
          onClick={async () => {
            await fetchClient.DELETE("/api/collections/{collection_id}/cover", { params: { path: { collection_id: collection.id } } });
            onChange();
          }}
        >
          {t("collections.removeCover")}
        </Button>
      )}
    </>
  );
}

function StoryArc({ arc, collectionId, admin }: { arc: Schemas["StoryArcOut"]; collectionId: number; admin: boolean }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const path = { params: { path: { collection_id: collectionId } } };
  const refresh = api.useMutation("post", "/api/collections/{collection_id}/story-arc/refresh");
  const requestMissing = api.useMutation("post", "/api/collections/{collection_id}/request-missing");
  const request = api.useMutation("post", "/api/requests");
  const owned = arc.issues.filter((i) => i.book_id != null).length;
  const missing = arc.issues.length - owned;
  const run = async (action: () => Promise<unknown>, done: string) => {
    try {
      await action();
      toast.success(done);
      await queryClient.invalidateQueries({ queryKey: ["get", "/api/collections/{collection_id}/story-arc"] });
    } catch (error) {
      toast.error(errorMessage(error, t("common.errorGeneric")));
    }
  };
  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-xl border bg-card px-4 py-3 text-sm">
        <span>
          {arc.issues.length === 0 ? t("collections.noRoster") : t("collections.owned", { owned, total: arc.issues.length })}
          {arc.roster_fetched_at && <span className="text-muted-foreground"> · {t("collections.fetched", { when: format.date(arc.roster_fetched_at) })}</span>}
        </span>
        <span className="flex gap-2">
          {missing > 0 && (
            <Button variant="outline" size="sm" disabled={requestMissing.isPending} onClick={() => void run(() => requestMissing.mutateAsync(path), t("collections.missingRequested"))}>
              <Inbox aria-hidden />
              {t("collections.requestMissing", { count: missing })}
            </Button>
          )}
          {admin && (
            <Button variant="outline" size="sm" disabled={refresh.isPending} onClick={() => void run(() => refresh.mutateAsync(path), t("collections.arcQueued"))}>
              <RefreshCw aria-hidden />
              {arc.issues.length === 0 ? t("collections.fetchRoster") : t("collections.updateRoster")}
            </Button>
          )}
        </span>
      </div>
      <CoverGrid>
        {arc.issues.map((issue) => (
          <li key={issue.id}>
            {issue.book_id != null ? (
              <Link to="/books/$bookId" params={{ bookId: issue.book_id }} className="group block rounded-lg">
                <Cover bookId={issue.book_id} alt="" className="shadow-sm ring-1 ring-foreground/5 transition-transform group-hover:-translate-y-0.5" />
                <div className="mt-2 line-clamp-2 text-sm font-medium">{issue.display_name}</div>
              </Link>
            ) : (
              <div>
                <div className="relative aspect-[2/3] overflow-hidden rounded-lg border border-dashed bg-muted">
                  {issue.cover_url && <img src={issue.cover_url} alt="" loading="lazy" referrerPolicy="no-referrer" className="h-full w-full object-cover opacity-40 grayscale" />}
                  <Badge variant="secondary" className="absolute top-2 left-2">{t("collections.missing")}</Badge>
                </div>
                <div className="mt-2 line-clamp-2 text-sm text-muted-foreground">{issue.display_name}</div>
                <button
                  type="button"
                  className="text-xs text-primary-text hover:underline"
                  onClick={() => void run(() => request.mutateAsync({ body: { title: issue.display_name, media_type: "series", external_link: issue.site_detail_url } }), t("releases.requested"))}
                >
                  {t("releases.request")}
                </button>
              </div>
            )}
          </li>
        ))}
      </CoverGrid>
    </div>
  );
}
