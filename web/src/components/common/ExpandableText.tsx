import { useLayoutEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { cn } from "@/lib/utils";

/** Long text clamped to a few lines, with a toggle when it overflows. */
export function ExpandableText({ text, lines = 4, className }: { text: string; lines?: number; className?: string }) {
  const { t } = useTranslation();
  const ref = useRef<HTMLParagraphElement>(null);
  const [open, setOpen] = useState(false);
  const [overflows, setOverflows] = useState(false);
  useLayoutEffect(() => {
    const element = ref.current;
    if (element) setOverflows(element.scrollHeight > element.clientHeight + 1);
  }, [text]);
  return (
    <div className={className}>
      <p ref={ref} className={cn("whitespace-pre-line", !open && "line-clamp-[var(--lines)]")} style={{ "--lines": lines } as React.CSSProperties}>
        {text}
      </p>
      {(overflows || open) && (
        <button type="button" onClick={() => setOpen(!open)} className="mt-1 text-xs font-medium text-primary-text hover:underline" aria-expanded={open}>
          {open ? t("common.showLess") : t("common.showMore")}
        </button>
      )}
    </div>
  );
}
