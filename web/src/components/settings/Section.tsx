import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

export function Section({ icon: Icon, title, description, children }: { icon: LucideIcon; title: string; description?: ReactNode; children: ReactNode }) {
  return (
    <section className="rounded-xl border bg-card p-5" aria-label={title}>
      <div className="mb-2 flex items-center gap-2">
        <span className="grid size-8 place-items-center rounded-lg bg-accent text-accent-foreground">
          <Icon className="size-4" aria-hidden />
        </span>
        <h2 className="text-lg font-semibold">{title}</h2>
      </div>
      {description && <div className="mb-4 text-sm text-muted-foreground">{description}</div>}
      {children}
    </section>
  );
}
