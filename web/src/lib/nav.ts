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
 * The main navigation, shared by the sidebar, the bottom tab bar and the
 * command palette. The tab bar has five fixed slots; the rest are in the
 * account menu on small screens.
 */
export interface NavItem {
  to: string;
  label: keyof (typeof sv)["nav"];
  icon: LucideIcon;
  adminOnly?: boolean;
  mobile?: boolean;
}

export const NAV_ITEMS: NavItem[] = [
  { to: "/", label: "home", icon: House, mobile: true },
  { to: "/libraries", label: "libraries", icon: Library, mobile: true },
  { to: "/search", label: "search", icon: Search },
  { to: "/following", label: "following", icon: BookMarked, mobile: true },
  { to: "/releases", label: "releases", icon: CalendarDays },
  { to: "/discover", label: "discover", icon: Sparkles },
  { to: "/collections", label: "collections", icon: Layers, mobile: true },
  { to: "/requests", label: "requests", icon: Inbox, mobile: true },
  { to: "/stats", label: "stats", icon: ChartColumn },
  { to: "/settings", label: "settings", icon: Settings },
  { to: "/admin", label: "admin", icon: ShieldCheck, adminOnly: true },
];
