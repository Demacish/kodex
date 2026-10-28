import { Link } from "@tanstack/react-router";

export function Logo() {
  return (
    <Link to="/" className="flex items-center gap-2 rounded-md px-1 text-lg font-semibold tracking-tight">
      <span aria-hidden className="grid size-7 place-items-center rounded-lg bg-primary text-sm font-bold text-primary-foreground">
        K
      </span>
      Kodex
    </Link>
  );
}
