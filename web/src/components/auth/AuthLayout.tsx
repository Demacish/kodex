import type { ReactNode } from "react";

/** The frame of the pages before login: the mark, a title and a card. */
export function AuthLayout({ title, intro, children }: { title: string; intro?: ReactNode; children: ReactNode }) {
  return (
    <main className="grid min-h-dvh place-items-center bg-gradient-to-b from-background to-muted/40 px-4">
      <div className="w-full max-w-sm space-y-6">
        <div className="text-center">
          <span aria-hidden className="mx-auto mb-4 grid size-12 place-items-center rounded-2xl bg-primary text-xl font-bold text-primary-foreground">
            K
          </span>
          <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
          {intro && <p className="mt-1 text-sm text-muted-foreground">{intro}</p>}
        </div>
        <div className="space-y-4 rounded-2xl border bg-card p-6 shadow-sm">{children}</div>
      </div>
    </main>
  );
}

export function OrDivider({ label }: { label: string }) {
  return (
    <div className="flex items-center gap-3 text-xs text-muted-foreground">
      <span className="h-px flex-1 bg-border" />
      {label}
      <span className="h-px flex-1 bg-border" />
    </div>
  );
}
