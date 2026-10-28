import { useNavigate, useSearch } from "@tanstack/react-router";
import { Search } from "lucide-react";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import { Input } from "@/components/ui/input";

import { AccountMenu } from "./AccountMenu";
import { Logo } from "./Logo";

export function TopBar() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const current = useSearch({ strict: false }) as { q?: string };
  const [query, setQuery] = useState(current.q ?? "");

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (query.trim()) void navigate({ to: "/search", search: { q: query.trim() } });
  };

  return (
    <header className="sticky top-0 z-20 flex h-14 items-center gap-3 border-b bg-background/90 px-4 backdrop-blur md:px-6">
      <div className="md:hidden">
        <Logo />
      </div>
      <form role="search" onSubmit={submit} className="relative ml-auto w-full max-w-md md:ml-0">
        <Search className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
        <Input
          type="search"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder={t("common.search")}
          aria-label={t("common.search")}
          className="pl-8"
        />
        <kbd className="pointer-events-none absolute top-1/2 right-2 hidden -translate-y-1/2 rounded border bg-muted px-1.5 text-[10px] text-muted-foreground lg:block">
          ⌘K
        </kbd>
      </form>
      <div className="ml-auto">
        <AccountMenu />
      </div>
    </header>
  );
}
