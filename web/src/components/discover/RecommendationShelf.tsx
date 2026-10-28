import { useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { Heart, X } from "lucide-react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { api, type Schemas } from "@/api/client";
import { Shelf, ShelfItem } from "@/components/library/Shelf";

type Recommendation = Schemas["AIRecommendationOut"];

export function useSwipe() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const swipe = api.useMutation("post", "/api/ai/recommendations/{recommendation_id}/swipe");
  return async (item: Recommendation, direction: "left" | "right") => {
    try {
      await swipe.mutateAsync({ params: { path: { recommendation_id: item.id } }, body: { direction } });
      if (direction === "right") toast.success(t("discover.requested", { title: item.title }));
      await queryClient.invalidateQueries({ queryKey: ["get", "/api/ai/recommendations"] });
    } catch {
      toast.error(t("common.errorGeneric"));
    }
  };
}

export function RecommendationCover({ item }: { item: Recommendation }) {
  return (
    <div className="relative aspect-[2/3] overflow-hidden rounded-lg bg-gradient-to-br from-accent to-muted shadow-sm ring-1 ring-foreground/5">
      {item.cover_url ? (
        <img src={item.cover_url} alt="" loading="lazy" referrerPolicy="no-referrer" className="h-full w-full object-cover" />
      ) : (
        <div className="grid h-full place-items-center p-3 text-center text-sm font-medium text-accent-foreground">{item.title}</div>
      )}
    </div>
  );
}

/** "For you" on the home page: what the AI suggests, if it is set up. */
export function RecommendationShelf() {
  const { t } = useTranslation();
  const recommendations = api.useQuery("get", "/api/ai/recommendations", {}, { retry: false });
  const swipe = useSwipe();
  const pending = recommendations.data?.filter((item) => item.status === "suggested") ?? [];
  if (pending.length === 0) return null;
  return (
    <Shelf title={t("home.forYou")} to="/discover">
      {pending.slice(0, 12).map((item) => (
        <ShelfItem key={item.id}>
          <div className="group relative">
            <Link to="/discover" className="block rounded-lg">
              <RecommendationCover item={item} />
            </Link>
            <div className="mt-2 line-clamp-2 text-sm leading-snug font-medium">{item.title}</div>
            {item.author && <div className="truncate text-xs text-muted-foreground">{item.author}</div>}
            <div className="absolute top-1.5 right-1.5 flex gap-1 opacity-0 transition group-focus-within:opacity-100 group-hover:opacity-100">
              <button type="button" onClick={() => void swipe(item, "left")} aria-label={t("discover.skip", { title: item.title })}
                className="grid size-7 place-items-center rounded-full bg-black/60 text-white hover:bg-black/80">
                <X className="size-3.5" aria-hidden />
              </button>
              <button type="button" onClick={() => void swipe(item, "right")} aria-label={t("discover.want", { title: item.title })}
                className="grid size-7 place-items-center rounded-full bg-primary text-primary-foreground hover:bg-primary/90">
                <Heart className="size-3.5" aria-hidden />
              </button>
            </div>
          </div>
        </ShelfItem>
      ))}
    </Shelf>
  );
}
