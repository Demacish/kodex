import { useQueryClient } from "@tanstack/react-query";
import { Tablet } from "lucide-react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { api, errorMessage } from "@/api/client";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { format } from "@/i18n";

const NONE = "none";

/** The address a Kobo e-reader is pointed at, for its config file. */
export function koboEndpoint(key: string): string {
  return `${window.location.origin}/kobo/${key}`;
}

/** Kobo e-readers (one per Kobo key) and the collection each syncs. */
export function KoboDevices() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const devices = api.useQuery("get", "/api/me/kobo");
  const collections = api.useQuery("get", "/api/collections");
  const update = api.useMutation("put", "/api/me/kobo/{key_id}", {
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["get", "/api/me/kobo"] }),
  });
  if (!devices.data?.length) return null;
  const manual = (collections.data ?? []).filter((c) => c.collection_type === "manual");
  return (
    <div className="mt-5 space-y-2">
      <h3 className="flex items-center gap-1.5 text-sm font-semibold"><Tablet className="size-4" aria-hidden />{t("settings.kobo.title")}</h3>
      <p className="text-xs text-muted-foreground">{t("settings.kobo.intro")}</p>
      <ul className="divide-y rounded-lg border" aria-label={t("settings.kobo.title")}>
        {devices.data.map((device) => (
          <li key={device.key_id} className="flex flex-wrap items-center gap-3 px-3 py-2 text-sm">
            <div className="min-w-0 flex-1">
              <div className="truncate font-medium">{device.name}</div>
              <div className="text-xs text-muted-foreground">
                {device.last_sync_at ? t("settings.kobo.synced", { when: format.relative(device.last_sync_at), count: device.books }) : t("settings.kobo.never")}
              </div>
            </div>
            <Select
              value={device.collection_id == null ? NONE : String(device.collection_id)}
              onValueChange={(value) =>
                update.mutate(
                  { params: { path: { key_id: device.key_id } }, body: { collection_id: value === NONE ? null : Number(value) } },
                  { onError: (error) => toast.error(errorMessage(error, t("common.errorGeneric"))) },
                )
              }
            >
              <SelectTrigger className="w-48" aria-label={t("settings.kobo.collection", { name: device.name })}>
                <SelectValue>
                  {(value: string) => (value === NONE ? t("settings.kobo.nothing") : manual.find((c) => String(c.id) === value)?.name ?? device.collection_name)}
                </SelectValue>
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={NONE}>{t("settings.kobo.nothing")}</SelectItem>
                {manual.map((c) => <SelectItem key={c.id} value={String(c.id)}>{c.name}</SelectItem>)}
              </SelectContent>
            </Select>
          </li>
        ))}
      </ul>
    </div>
  );
}
