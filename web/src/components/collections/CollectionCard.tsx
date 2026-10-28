import { Link } from "@tanstack/react-router";
import { Layers, Sparkles } from "lucide-react";
import { useTranslation } from "react-i18next";

import type { Schemas } from "@/api/client";
import { Badge } from "@/components/ui/badge";

export function CollectionCard({ collection }: { collection: Schemas["CollectionOut"] }) {
  const { t } = useTranslation();
  const src = collection.has_custom_cover
    ? `/api/collections/${collection.id}/cover`
    : collection.cover_book_id
      ? `/api/books/${collection.cover_book_id}/cover?size=medium`
      : null;
  return (
    <Link to="/collections/$collectionId" params={{ collectionId: collection.id }} className="group block rounded-lg">
      <div className="relative aspect-[2/3] overflow-hidden rounded-lg bg-muted shadow-sm ring-1 ring-foreground/5 transition-transform group-hover:-translate-y-0.5">
        {src ? (
          <img src={src} alt="" loading="lazy" className="h-full w-full object-cover" />
        ) : (
          <div className="grid h-full place-items-center text-muted-foreground">
            {collection.story_arc_id ? <Sparkles className="size-8" aria-hidden /> : <Layers className="size-8" aria-hidden />}
          </div>
        )}
        <Badge className="absolute top-2 right-2 bg-black/70 text-white">{t("collections.books", { count: collection.book_count })}</Badge>
        {collection.story_arc_id && (
          <Badge className="absolute top-2 left-2">
            <Sparkles aria-hidden />
            {t("collections.storyArc")}
          </Badge>
        )}
      </div>
      <div className="mt-2 line-clamp-2 text-sm font-medium">{collection.name}</div>
      <div className="text-xs text-muted-foreground">
        {t(`collections.types.${collection.collection_type as "manual" | "smart"}`)}
        {collection.owner_user_id != null && ` · ${t("collections.personal")}`}
      </div>
    </Link>
  );
}
