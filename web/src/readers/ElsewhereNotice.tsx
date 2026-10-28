import { MonitorSmartphone } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { format } from "@/i18n";

import type { Progress } from "./useProgress";

/** "You read further on another device": jump there, or stay. */
export function ElsewhereNotice({ progress, label, onJump, onDismiss }: {
  progress: Progress;
  label: string;
  onJump: () => void;
  onDismiss: () => void;
}) {
  const { t } = useTranslation();
  return (
    <div role="status" className="fixed inset-x-0 top-14 z-50 mx-auto flex w-fit max-w-[calc(100%-2rem)] flex-wrap items-center gap-3 rounded-xl border border-white/10 bg-neutral-900/95 px-4 py-3 text-sm text-white shadow-xl backdrop-blur">
      <MonitorSmartphone className="size-4 shrink-0 text-primary-text" aria-hidden />
      <span>
        {t("reader.elsewhere", { device: progress.device_name ?? t("reader.anotherDevice"), where: label, when: format.relative(progress.last_read_at) })}
      </span>
      <span className="flex gap-2">
        <Button size="sm" onClick={onJump}>{t("reader.jump")}</Button>
        <Button size="sm" variant="ghost" className="text-white hover:bg-white/10 hover:text-white" onClick={onDismiss}>{t("reader.stay")}</Button>
      </span>
    </div>
  );
}
