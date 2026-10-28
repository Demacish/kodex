import { useQueryClient } from "@tanstack/react-query";
import { createFileRoute, Link } from "@tanstack/react-router";
import { Flag } from "lucide-react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { api } from "@/api/client";
import { EmptyState, ErrorState, PageHeader } from "@/components/common/states";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { format } from "@/i18n";
import { oneOf, searchSchema } from "@/lib/search";

const search = searchSchema({ all: "no" as "no" | "yes" }, { all: oneOf(["no", "yes"] as const) });

export const Route = createFileRoute("/_authed/_shell/admin/page-flags")({
  validateSearch: search.validate,
  component: PageFlags,
});

/** Pages readers flagged: delete (hidden in the reader, the file is untouched) or keep. */
function PageFlags() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const { all } = search.resolve(Route.useSearch());
  const navigate = Route.useNavigate();
  const flags = api.useQuery("get", "/api/page-flags", { params: { query: all === "yes" ? {} : { resolved: false } } });
  const resolve = api.useMutation("post", "/api/books/{book_id}/pages/{page_index}/resolve");
  const act = async (bookId: number, page: number, action: "deleted" | "kept") => {
    try {
      await resolve.mutateAsync({ params: { path: { book_id: bookId, page_index: page } }, body: { action } });
      toast.success(t(`pageFlags.done.${action}`));
      await queryClient.invalidateQueries({ queryKey: ["get", "/api/page-flags"] });
    } catch {
      toast.error(t("common.errorGeneric"));
    }
  };
  return (
    <div>
      <PageHeader
        title={t("admin.nav.pageFlags")}
        description={t("pageFlags.intro")}
        actions={
          <label className="flex items-center gap-2 text-sm">
            {t("pageFlags.showResolved")}
            <Switch checked={all === "yes"} onCheckedChange={(on) => navigate({ search: search.update({ all: on ? "yes" : "no" }) })} />
          </label>
        }
      />
      {flags.isError ? (
        <ErrorState error={flags.error} onRetry={() => void flags.refetch()} />
      ) : flags.isPending ? (
        <Skeleton className="h-48 rounded-xl" />
      ) : flags.data.length === 0 ? (
        <EmptyState icon={Flag} title={t("pageFlags.none")} />
      ) : (
        <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {flags.data.map((flag) => (
            <li key={flag.id} className="flex gap-3 rounded-xl border bg-card p-3">
              <a href={`/api/books/${flag.book_id}/pages/${flag.page_index}?max_width=480`} target="_blank" rel="noreferrer" className="shrink-0">
                <img src={`/api/books/${flag.book_id}/pages/${flag.page_index}?max_width=480`} alt={t("reader.page", { page: flag.page_index + 1, total: "?" })} loading="lazy" className="h-36 w-24 rounded bg-muted object-contain" />
              </a>
              <div className="min-w-0 flex-1 space-y-1 text-sm">
                <Link to="/books/$bookId/read" params={{ bookId: flag.book_id }} search={{ pos: String(flag.page_index) }} className="line-clamp-2 font-medium hover:text-primary-text">
                  {flag.book_title}
                </Link>
                <div className="text-xs text-muted-foreground">
                  {t("reader.pageShort", { page: flag.page_index + 1 })} · {t(`reader.flagReasons.${flag.reason}`)}
                </div>
                <div className="text-xs text-muted-foreground">{[flag.flagged_by_username, format.relative(flag.flagged_at)].filter(Boolean).join(" · ")}</div>
                {flag.note && <p className="text-xs">{flag.note}</p>}
                {flag.resolved ? (
                  <Badge variant="secondary">{t(`pageFlags.done.${flag.resolved_action ?? "kept"}`)}</Badge>
                ) : (
                  <div className="flex gap-2 pt-1">
                    <Button size="sm" variant="destructive" onClick={() => void act(flag.book_id, flag.page_index, "deleted")}>{t("pageFlags.delete")}</Button>
                    <Button size="sm" variant="outline" onClick={() => void act(flag.book_id, flag.page_index, "kept")}>{t("pageFlags.keep")}</Button>
                  </div>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
