import { useQueryClient } from "@tanstack/react-query";
import { createFileRoute } from "@tanstack/react-router";
import { Heart, RefreshCw, Sparkles, X } from "lucide-react";
import { useEffect } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { api, errorMessage } from "@/api/client";
import { EmptyState, ErrorState, PageHeader } from "@/components/common/states";
import { RecommendationCover, useSwipe } from "@/components/discover/RecommendationShelf";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";

export const Route = createFileRoute("/_authed/_shell/discover")({
  component: Discover,
});

/** One suggestion at a time: want it (a request) or skip it. Arrow keys work too. */
function Discover() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const recommendations = api.useQuery("get", "/api/ai/recommendations");
  const generate = api.useMutation("post", "/api/ai/recommendations/generate");
  const swipe = useSwipe();
  const current = recommendations.data?.[0];

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (!current || (event.target as HTMLElement | null)?.closest("input, textarea")) return;
      if (event.key === "ArrowRight") void swipe(current, "right");
      if (event.key === "ArrowLeft") void swipe(current, "left");
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [current, swipe]);

  const more = async () => {
    try {
      await generate.mutateAsync({});
      await queryClient.invalidateQueries({ queryKey: ["get", "/api/ai/recommendations"] });
    } catch (error) {
      toast.error(errorMessage(error, t("discover.failed")));
    }
  };

  return (
    <div className="mx-auto max-w-md">
      <PageHeader title={t("nav.discover")} description={t("discover.intro")} />
      {recommendations.isError ? (
        <ErrorState error={recommendations.error} onRetry={() => void recommendations.refetch()} />
      ) : recommendations.isPending ? (
        <Skeleton className="aspect-[2/3] w-full rounded-2xl" />
      ) : !current ? (
        <EmptyState icon={Sparkles} title={t("discover.empty")}>
          <p className="mb-3">{t("discover.emptyText")}</p>
          <Button onClick={() => void more()} disabled={generate.isPending}>
            <RefreshCw className={generate.isPending ? "animate-spin" : undefined} aria-hidden />
            {t("discover.generate")}
          </Button>
        </EmptyState>
      ) : (
        <div className="space-y-4">
          <article aria-label={current.title} className="overflow-hidden rounded-2xl border bg-card shadow-lg">
            <div className="mx-auto w-2/3 pt-6">
              <RecommendationCover item={current} />
            </div>
            <div className="space-y-1 p-5">
              <h2 className="text-lg font-semibold">{current.title}</h2>
              {current.author && <p className="text-sm text-muted-foreground">{current.author}</p>}
              {current.reason && <p className="pt-2 text-sm leading-relaxed">{current.reason}</p>}
            </div>
          </article>
          <div className="flex justify-center gap-6">
            <Button variant="outline" size="icon-lg" className="size-14 rounded-full" onClick={() => void swipe(current, "left")} aria-label={t("discover.skip", { title: current.title })}>
              <X className="size-6" aria-hidden />
            </Button>
            <Button size="icon-lg" className="size-14 rounded-full" onClick={() => void swipe(current, "right")} aria-label={t("discover.want", { title: current.title })}>
              <Heart className="size-6" aria-hidden />
            </Button>
          </div>
          <p className="text-center text-xs text-muted-foreground">{t("discover.left", { count: recommendations.data.length })}</p>
        </div>
      )}
    </div>
  );
}
