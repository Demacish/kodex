import { Link } from "@tanstack/react-router";
import { Check, LogOut, Monitor, Moon, Sun } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { LANGUAGES, setLanguage, type Language } from "@/i18n";
import { useAccount, useLogout } from "@/lib/account";
import { NAV_ITEMS } from "@/lib/nav";
import { useTheme, type Theme } from "@/lib/theme";

const THEMES: { value: Theme; icon: typeof Sun }[] = [
  { value: "system", icon: Monitor },
  { value: "light", icon: Sun },
  { value: "dark", icon: Moon },
];

export function AccountMenu() {
  const { t, i18n } = useTranslation();
  const account = useAccount();
  const logout = useLogout();
  const { theme, setTheme } = useTheme();
  const extra = NAV_ITEMS.filter((item) => !item.mobile && (!item.adminOnly || account.is_admin));
  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        render={<Button variant="ghost" size="icon" className="rounded-full" aria-label={t("account.menu")} />}
      >
        <span className="grid size-8 place-items-center rounded-full bg-secondary text-sm font-semibold uppercase">
          {account.username.slice(0, 1)}
        </span>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-60">
        <DropdownMenuGroup>
          <DropdownMenuLabel>
            <div className="truncate text-sm font-medium text-foreground">{account.username}</div>
            <div className="text-xs font-normal">{t(`account.roles.${account.role as "admin" | "user" | "guest"}`)}</div>
          </DropdownMenuLabel>
        </DropdownMenuGroup>
        <DropdownMenuSeparator className="md:hidden" />
        <DropdownMenuGroup className="md:hidden">
          {extra.map((item) => (
            <DropdownMenuItem key={item.to} render={<Link to={item.to} />}>
              <item.icon aria-hidden />
              {t(`nav.${item.label}`)}
            </DropdownMenuItem>
          ))}
        </DropdownMenuGroup>
        <DropdownMenuSeparator />
        <DropdownMenuGroup>
          <DropdownMenuLabel>{t("theme.label")}</DropdownMenuLabel>
          <DropdownMenuRadioGroup value={theme} onValueChange={(value) => setTheme(value as Theme)}>
            {THEMES.map(({ value, icon: Icon }) => (
              <DropdownMenuRadioItem key={value} value={value}>
                <Icon aria-hidden />
                {t(`theme.${value}`)}
              </DropdownMenuRadioItem>
            ))}
          </DropdownMenuRadioGroup>
        </DropdownMenuGroup>
        <DropdownMenuSeparator />
        <DropdownMenuGroup>
          <DropdownMenuLabel>{t("language.label")}</DropdownMenuLabel>
          {LANGUAGES.map((language: Language) => (
            <DropdownMenuItem key={language} onClick={() => setLanguage(language)} lang={language}>
              {i18n.language === language ? <Check aria-hidden /> : <span className="size-4" aria-hidden />}
              {t(`language.${language}`)}
            </DropdownMenuItem>
          ))}
        </DropdownMenuGroup>
        {account.auth_method === "session" && (
          <>
            <DropdownMenuSeparator />
            <DropdownMenuItem onClick={() => void logout()}>
              <LogOut aria-hidden />
              {t("account.logout")}
            </DropdownMenuItem>
          </>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
