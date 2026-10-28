import { createFileRoute, Link } from "@tanstack/react-router";
import { Sparkles } from "lucide-react";
import { Fragment, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { api } from "@/api/client";
import { CoverGridSkeleton, EmptyState, ErrorState } from "@/components/common/states";
import { BookCard } from "@/components/library/BookCard";
import { ContinueCard } from "@/components/library/ContinueCard";
import { LibraryCard } from "@/components/library/LibraryCard";
import { Shelf, ShelfItem } from "@/components/library/Shelf";
import { RecommendationShelf } from "@/components/discover/RecommendationShelf";
import { useAccount } from "@/lib/account";
import { HOME_SECTIONS, type HomeSection } from "@/lib/home";

export const Route = createFileRoute("/_authed/_shell/")({
  component: Home,
});

const SHELF = 12;
const NEW_IN_FOLLOWED_DAYS = 60;

function Home() {
  const { t } = useTranslation();
  const account = useAccount();
  const profile = api.useQuery("get", "/api/me");
  const continueReading = api.useQuery("get", "/api/me/continue-reading");
  const libraries = api.useQuery("get", "/api/libraries");
  const followed = api.useQuery("get", "/api/series", { params: { query: { following: true, limit: 500 } } });
  const newInFollowed = api.useQuery("get", "/api/books", {
    params: { query: { following_only: true, added_within_days: NEW_IN_FOLLOWED_DAYS, read_status: "unread", sort: "added_at", order: "desc", limit: SHELF } },
  });
  const newlyAdded = api.useQuery("get", "/api/books", { params: { query: { sort: "added_at", order: "desc", limit: SHELF } } });
  const updated = api.useQuery("get", "/api/books", { params: { query: { sort: "updated_at", order: "desc", limit: SHELF } } });

  if (libraries.isError) return <ErrorState error={libraries.error} onRetry={() => void libraries.refetch()} />;
  if (libraries.isPending || profile.isPending) return <CoverGridSkeleton />;

  const newReleases = followed.data?.filter((s) => s.new_release_available).length ?? 0;
  const bookShelf = (title: string, books: typeof newlyAdded.data, to?: string, search?: Record<string, unknown>) =>
    books && books.length > 0 ? (
      <Shelf title={title} to={to} search={search}>
        {books.map((book) => (
          <ShelfItem key={book.id}>
            <BookCard book={book} />
          </ShelfItem>
        ))}
      </Shelf>
    ) : null;

  const sections: Record<HomeSection, ReactNode> = {
    ai_recommendations: <RecommendationShelf />,
    continue_reading:
      continueReading.data && continueReading.data.length > 0 ? (
        <Shelf title={t("home.continueReading")}>
          {continueReading.data.map((item) => (
            <ShelfItem key={item.book_id}>
              <ContinueCard item={item} />
            </ShelfItem>
          ))}
        </Shelf>
      ) : null,
    new_in_followed: bookShelf(t("home.newInFollowed"), newInFollowed.data, "/following"),
    newly_added: bookShelf(t("home.newlyAdded"), newlyAdded.data),
    recently_updated: bookShelf(t("home.recentlyUpdated"), updated.data),
    libraries: (
      <section className="mb-10">
        <h2 className="mb-3 text-lg font-semibold tracking-tight">{t("nav.libraries")}</h2>
        {libraries.data.length === 0 ? (
          <EmptyState title={t("home.noLibraries")}>
            {account.is_admin ? (
              <Link to="/admin/libraries" className="text-primary-text hover:underline">
                {t("home.createLibrary")}
              </Link>
            ) : (
              t("home.noLibrariesUser")
            )}
          </EmptyState>
        ) : (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {libraries.data.map((library) => (
              <LibraryCard key={library.id} library={library} />
            ))}
          </div>
        )}
      </section>
    ),
  };
  const order = (profile.data?.home_sections as HomeSection[] | null | undefined) ?? HOME_SECTIONS;

  return (
    <div>
      <h1 className="sr-only">{t("nav.home")}</h1>
      {newReleases > 0 && (
        <Link
          to="/following"
          className="mb-6 flex items-center gap-2 rounded-xl border border-primary/25 bg-primary/5 px-4 py-3 text-sm text-primary-text transition hover:bg-primary/10"
        >
          <Sparkles className="size-4 shrink-0" aria-hidden />
          {t("home.newReleases", { count: newReleases })}
        </Link>
      )}
      {order.map((key) => (
        <Fragment key={key}>{sections[key]}</Fragment>
      ))}
    </div>
  );
}
