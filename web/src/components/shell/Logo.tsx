import { Link } from "@tanstack/react-router";

/** The mark and the name; `compact` shows the name only from lg (the rail is too narrow for it). */
export function Logo({ compact = false }: { compact?: boolean }) {
  return (
    <Link to="/" className="flex items-center gap-2 rounded-md px-1 text-lg font-semibold tracking-tight">
      <span aria-hidden className="grid size-7 place-items-center rounded-lg bg-primary text-sm font-bold text-primary-foreground">
        K
      </span>
      <span className={compact ? "max-lg:sr-only" : undefined}>Kodex</span>
    </Link>
  );
}
