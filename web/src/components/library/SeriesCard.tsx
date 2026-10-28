import { useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { Bell, BellOff, CircleCheck } from "lucide-react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { api, type Schemas } from "@/api/client";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";

import { Cover } from "./Cover";

type Series = Schemas["SeriesOut"];

export function useFollow(series: Pick<Series, "id" | "is_following">) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const follow = api.useMutation("post", "/api/series/{series_id}/follow");
  const unfollow = api.useMutation("post", "/api/series/{series_id}/unfollow");
  const pending = follow.isPending || unfollow.isPending;
  const toggle = async () => {
    const mutation = series.is_following ? unfollow : follow;
    try {
      await mutation.mutateAsync({ params: { path: { series_id: series.id } } });
      toast.success(series.is_following ? t("series.unfollowed") : t("series.followed"));
      await queryClient.invalidateQueries({ queryKey: ["get", "/api/series"] });
      await queryClient.invalidateQueries({ queryKey: ["get", "/api/series/{series_id}"] });
    } catch {
      toast.error(t("series.followFailed"));
    }
  };
  return { toggle, pending };
}

export function SeriesCard({ series }: { series: Series }) {
  const { t } = useTranslation();
  const { toggle, pending } = useFollow(series);
  const allRead = series.book_count > 0 && series.read_count === series.book_count;
  return (
    <div className="group relative">
      <Link to="/series/$seriesId" params={{ seriesId: series.id }} className="block rounded-lg">
        <div className="transition-transform duration-200 group-hover:-translate-y-0.5">
          <Cover bookId={series.cover_book_id} alt="" className="shadow-sm ring-1 ring-foreground/5" />
        </div>
        <div className="mt-2 flex items-start gap-1.5">
          <span className="line-clamp-2 text-sm leading-snug font-medium">{series.title}</span>
        </div>
        <div className="mt-0.5 flex items-center gap-1 text-xs text-muted-foreground">
          {allRead && <CircleCheck className="size-3.5 text-primary-text" aria-hidden />}
          {t("series.readCount", { read: series.read_count, count: series.book_count })}
        </div>
        {series.read_count > 0 && !allRead && (
          <Progress value={(series.read_count / series.book_count) * 100} className="mt-1 h-1" aria-hidden />
        )}
      </Link>
      {series.new_release_available && (
        <Badge className="absolute top-2 right-2 shadow-sm">{t("series.newRelease")}</Badge>
      )}
      <button
        type="button"
        onClick={() => void toggle()}
        disabled={pending}
        aria-pressed={series.is_following}
        aria-label={series.is_following ? t("series.unfollow") : t("series.follow")}
        title={series.is_following ? t("series.unfollow") : t("series.follow")}
        className="absolute top-2 left-2 grid size-7 place-items-center rounded-full bg-black/60 text-white opacity-0 shadow-sm transition group-focus-within:opacity-100 group-hover:opacity-100 hover:bg-black/75 focus-visible:opacity-100 disabled:opacity-60 data-[on=true]:opacity-100"
        data-on={series.is_following}
      >
        {series.is_following ? <Bell className="size-3.5" aria-hidden /> : <BellOff className="size-3.5" aria-hidden />}
      </button>
    </div>
  );
}
