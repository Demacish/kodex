import { createFileRoute, Link, Outlet, redirect } from "@tanstack/react-router";
import { BarChart3, Copy, FileQuestion, FileUp, Flag, GitCompareArrows, Library, ListTodo, Plug, Users } from "lucide-react";
import { useTranslation } from "react-i18next";

import type sv from "@/i18n/sv.json";

const ITEMS: { to: string; label: keyof (typeof sv)["admin"]["nav"]; icon: typeof Library }[] = [
  { to: "/admin", label: "review", icon: GitCompareArrows },
  { to: "/admin/libraries", label: "libraries", icon: Library },
  { to: "/admin/jobs", label: "jobs", icon: ListTodo },
  { to: "/admin/import", label: "import", icon: FileUp },
  { to: "/admin/duplicates", label: "duplicates", icon: Copy },
  { to: "/admin/page-flags", label: "pageFlags", icon: Flag },
  { to: "/admin/missing", label: "missing", icon: FileQuestion },
  { to: "/admin/users", label: "users", icon: Users },
  { to: "/admin/integrations", label: "integrations", icon: Plug },
  { to: "/admin/stats", label: "stats", icon: BarChart3 },
];

export const Route = createFileRoute("/_authed/_shell/admin")({
  beforeLoad: ({ context }) => {
    if (!context.account.is_admin) throw redirect({ to: "/" });
  },
  component: AdminLayout,
});

function AdminLayout() {
  const { t } = useTranslation();
  return (
    <div>
      <nav aria-label={t("admin.navLabel")} className="-mx-4 mb-6 overflow-x-auto border-b px-4 md:mx-0 md:px-0">
        <ul className="flex min-w-max gap-1">
          {ITEMS.map((item) => (
            <li key={item.to}>
              <Link
                to={item.to}
                activeOptions={{ exact: item.to === "/admin" }}
                className="-mb-px flex items-center gap-1.5 border-b-2 border-transparent px-3 py-2 text-sm text-muted-foreground transition hover:text-foreground"
                activeProps={{ className: "border-primary text-foreground", "aria-current": "page" }}
              >
                <item.icon className="size-4" aria-hidden />
                {t(`admin.nav.${item.label}`)}
              </Link>
            </li>
          ))}
        </ul>
      </nav>
      <Outlet />
    </div>
  );
}
