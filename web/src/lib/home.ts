/** The home page's shelves, in their default order (backend: HOME_SECTION_KEYS). */
export const HOME_SECTIONS = [
  "ai_recommendations",
  "continue_reading",
  "new_in_followed",
  "newly_added",
  "recently_updated",
  "libraries",
] as const;
export type HomeSection = (typeof HOME_SECTIONS)[number];
