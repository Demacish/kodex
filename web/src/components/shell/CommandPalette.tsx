import { useNavigate } from "@tanstack/react-router";
import { Search } from "lucide-react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import { useAccount } from "@/lib/account";
import { NAV_ITEMS } from "@/lib/nav";

/** ⌘K / Ctrl+K: jump to a page, or search for what was typed. */
export function CommandPalette() {
  const { t } = useTranslation();
  const account = useAccount();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key.toLowerCase() === "k" && (event.metaKey || event.ctrlKey)) {
        event.preventDefault();
        setOpen((value) => !value);
      }
    };
    const onOpen = () => setOpen(true);
    window.addEventListener("keydown", onKey);
    window.addEventListener("kodex:command-palette", onOpen);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("kodex:command-palette", onOpen);
    };
  }, []);

  const go = (to: string, search?: Record<string, string>) => {
    setOpen(false);
    setQuery("");
    void navigate({ to, search });
  };

  return (
    <CommandDialog open={open} onOpenChange={setOpen} title={t("nav.commandPalette")} description={t("nav.commandPlaceholder")}>
      <CommandInput placeholder={t("nav.commandPlaceholder")} value={query} onValueChange={setQuery} />
      <CommandList>
        <CommandEmpty>{t("nav.commandEmpty")}</CommandEmpty>
        {query.trim() && (
          <CommandGroup>
            <CommandItem value={`search ${query}`} onSelect={() => go("/search", { q: query.trim() })}>
              <Search aria-hidden />
              {t("nav.searchFor", { query: query.trim() })}
            </CommandItem>
          </CommandGroup>
        )}
        <CommandGroup heading={t("nav.main")}>
          {NAV_ITEMS.filter((item) => !item.adminOnly || account.is_admin).map((item) => (
            <CommandItem key={item.to} value={t(`nav.${item.label}`)} onSelect={() => go(item.to)}>
              <item.icon aria-hidden />
              {t(`nav.${item.label}`)}
            </CommandItem>
          ))}
        </CommandGroup>
      </CommandList>
    </CommandDialog>
  );
}
