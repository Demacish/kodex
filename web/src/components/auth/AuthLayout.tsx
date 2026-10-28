import { Eye, EyeOff } from "lucide-react";
import { useState, type ComponentProps, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

/**
 * The frame of the pages before login (logging in, the first admin, the
 * second step, a sign-in link, approving an app): a dark backdrop with the
 * accent's glow, the mark, a title and a card. On a phone the page runs top
 * to bottom; from sm up the card sits in the middle. Light mode is the same
 * on the light surfaces.
 */
export function AuthLayout({ title, intro, children, footer }: { title: string; intro?: ReactNode; children: ReactNode; footer?: ReactNode }) {
  return (
    <div className="relative isolate min-h-dvh overflow-x-hidden bg-background dark:bg-[#0a0c10]">
      <div aria-hidden className="pointer-events-none fixed inset-0 -z-10 overflow-hidden">
        <div className="absolute -top-40 left-1/2 h-[500px] w-[700px] -translate-x-1/2 rounded-full bg-primary/10 blur-[140px]" />
        <div className="absolute right-1/4 bottom-0 h-[300px] w-[400px] rounded-full bg-orange-600/5 blur-[120px]" />
        <div className="auth-grid absolute inset-0 opacity-60 max-sm:hidden" />
      </div>
      <main className="mx-auto flex min-h-dvh w-full max-w-[460px] flex-col px-5 pt-10 pb-8 sm:justify-center sm:px-6">
        <header className="mb-8 flex flex-col items-center text-center">
          <span
            aria-hidden
            className="mb-5 grid size-14 place-items-center rounded-2xl bg-gradient-to-tr from-[#c2410c] to-[#ea580c] text-2xl font-bold text-white shadow-lg shadow-primary/25 ring-1 ring-white/20"
          >
            K
          </span>
          <h1 className="text-[28px] leading-tight font-bold tracking-tight sm:text-3xl">{title}</h1>
          {intro && <p className="mt-2 text-sm text-muted-foreground dark:text-slate-400">{intro}</p>}
        </header>
        <div className="space-y-5 rounded-2xl border bg-card/90 p-5 shadow-xl shadow-black/5 backdrop-blur-xl sm:p-7 lg:p-9 dark:border-white/[0.07] dark:bg-[#141721]/90 dark:shadow-2xl dark:shadow-black/60">
          {children}
        </div>
        {footer && <footer className="mt-6 text-center text-xs text-muted-foreground dark:text-slate-400">{footer}</footer>}
      </main>
    </div>
  );
}

/** A labelled field: the label in small capitals, something beside it (a link), and a hint below. */
export function AuthField({ id, label, aside, hint, children }: { id: string; label: string; aside?: ReactNode; hint?: ReactNode; children: ReactNode }) {
  return (
    <div>
      <div className="mb-2 flex items-center justify-between gap-3">
        <label htmlFor={id} className="text-[11px] font-semibold tracking-wider text-muted-foreground uppercase sm:text-xs dark:text-slate-300">
          {label}
        </label>
        {aside}
      </div>
      {children}
      {hint && (
        <p id={`${id}-hint`} className="mt-1.5 text-xs text-muted-foreground dark:text-slate-400">
          {hint}
        </p>
      )}
    </div>
  );
}

const authInput =
  "h-12 rounded-xl bg-muted/50 px-4 text-base placeholder:text-muted-foreground/70 focus-visible:border-primary focus-visible:ring-2 focus-visible:ring-primary/20 md:text-sm dark:border-white/[0.12] dark:bg-[#1a1e2b]/80 dark:placeholder:text-slate-500";

export function AuthInput({ className, ...props }: ComponentProps<typeof Input>) {
  return <Input className={cn(authInput, className)} {...props} />;
}

/** A password field with a button that shows what was typed. */
export function PasswordInput({ className, id, ...props }: Omit<ComponentProps<typeof Input>, "type">) {
  const { t } = useTranslation();
  const [shown, setShown] = useState(false);
  return (
    <div className="relative">
      <AuthInput id={id} type={shown ? "text" : "password"} className={cn("pr-11", className)} {...props} />
      <button
        type="button"
        aria-label={shown ? t("auth.hidePassword") : t("auth.showPassword")}
        aria-controls={id}
        aria-pressed={shown}
        onClick={() => setShown((value) => !value)}
        className="absolute inset-y-0 right-0 flex items-center rounded-r-xl pr-3.5 pl-2 text-muted-foreground transition-colors outline-none hover:text-foreground focus-visible:text-foreground focus-visible:ring-2 focus-visible:ring-primary/40 dark:text-slate-400 dark:hover:text-slate-200"
      >
        {shown ? <EyeOff aria-hidden className="size-4" /> : <Eye aria-hidden className="size-4" />}
      </button>
    </div>
  );
}

/** The card's main action: the accent's gradient, white text that meets WCAG AA at both ends. */
export function AuthSubmit({ className, ...props }: ComponentProps<typeof Button>) {
  return (
    <Button
      className={cn(
        "h-12 w-full rounded-xl bg-gradient-to-r from-[#c2410c] to-[#d2460c] text-sm font-semibold tracking-wide text-white shadow-lg shadow-primary/20 transition-all duration-200 hover:from-[#b23b0b] hover:to-[#c2410c] hover:shadow-primary/35 active:scale-[0.99]",
        className,
      )}
      {...props}
    />
  );
}

/** Another way in (a passkey, the identity provider), or a way back. */
export function AuthSecondary({ className, ...props }: ComponentProps<typeof Button>) {
  return (
    <Button
      variant="outline"
      className={cn(
        "group h-12 w-full gap-2.5 rounded-xl bg-muted/60 text-sm font-medium transition-all duration-200 hover:bg-muted active:scale-[0.99] dark:border-white/[0.07] dark:bg-[#1a1e2b]/90 dark:hover:border-slate-600 dark:hover:bg-slate-800/90 [&_svg]:text-muted-foreground group-hover:[&_svg]:text-primary-text",
        className,
      )}
      {...props}
    />
  );
}

export function OrDivider({ label }: { label: string }) {
  return (
    <div className="flex items-center gap-3 py-1 text-xs font-medium tracking-wide text-muted-foreground lowercase dark:text-slate-400">
      <span className="h-px flex-1 bg-border dark:bg-white/[0.08]" />
      {label}
      <span className="h-px flex-1 bg-border dark:bg-white/[0.08]" />
    </div>
  );
}
