import {
  BookMarked,
  CalendarDays,
  ChartColumn,
  House,
  Inbox,
  Layers,
  Library,
  Search,
  Settings,
  ShieldCheck,
  Sparkles,
  type LucideIcon,
} from "lucide-react";

import type sv from "@/i18n/sv.json";

/**
 * The main navigation, shared by the sidebar, the rail, the bottom tab bar
 * and the command palette. On a phone the tab bar has the ones marked
 * `mobile` and Mer, a sheet with the rest.
 */
export interface NavItem {
  to: string;
  label: keyof (typeof sv)["nav"];
  icon: LucideIcon;
  adminOnly?: boolean;
  mobile?: boolean;
  /** Other pages that belong to it (a series and a book belong to the libraries). */
  also?: string[];
}

/** Whether ``item`` is the page at ``pathname``, or one of its own. */
export function isCurrent(item: NavItem, pathname: string): boolean {
  const under = (to: string) => pathname === to || pathname.startsWith(`${to}/`);
  return item.to === "/" ? pathname === "/" : under(item.to) || (item.also ?? []).some(under);
}

export const NAV_ITEMS: NavItem[] = [
  { to: "/", label: "home", icon: House, mobile: true },
  { to: "/libraries", label: "libraries", icon: Library, mobile: true, also: ["/series", "/books"] },
  { to: "/search", label: "search", icon: Search },
  { to: "/following", label: "following", icon: BookMarked, mobile: true },
  { to: "/releases", label: "releases", icon: CalendarDays },
  { to: "/discover", label: "discover", icon: Sparkles },
  { to: "/collections", label: "collections", icon: Layers, mobile: true },
  { to: "/requests", label: "requests", icon: Inbox },
  { to: "/stats", label: "stats", icon: ChartColumn },
  { to: "/settings", label: "settings", icon: Settings },
  { to: "/admin", label: "admin", icon: ShieldCheck, adminOnly: true },
];
