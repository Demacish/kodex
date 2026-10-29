import type { ReactNode } from "react";

export function CoverGrid({ children, label }: { children: ReactNode; label?: string }) {
  return (
    <ul aria-label={label} className="grid grid-cols-3 gap-x-3 gap-y-5 sm:grid-cols-4 sm:gap-x-4 sm:gap-y-6 md:grid-cols-5 xl:grid-cols-6">
      {children}
    </ul>
  );
}
