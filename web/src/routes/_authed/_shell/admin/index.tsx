import { createFileRoute } from "@tanstack/react-router";

import { ReviewQueue } from "@/components/admin/ReviewQueue";
import { oneOf, searchSchema } from "@/lib/search";

const TABS = ["open", "auto", "resolved", "dismissed"] as const;
const reviewSearch = searchSchema({ tab: "open" as (typeof TABS)[number] }, { tab: oneOf(TABS) });

export const Route = createFileRoute("/_authed/_shell/admin/")({
  validateSearch: reviewSearch.validate,
  component: () => {
    const { tab } = reviewSearch.resolve(Route.useSearch());
    const navigate = Route.useNavigate();
    return <ReviewQueue tab={tab} onTab={(next) => void navigate({ search: reviewSearch.update({ tab: next }) })} />;
  },
});
