import { Server } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { api, errorMessage, fetchClient, type Schemas } from "@/api/client";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

/** Which of the series' books other Kodex servers have, and copying the rest there. */
export function SeriesPeers({ seriesId }: { seriesId: number }) {
  const { t } = useTranslation();
  const peers = api.useQuery("get", "/api/peers");
  const status = api.useQuery("get", "/api/peers/series/{series_id}", { params: { path: { series_id: seriesId } } }, { enabled: (peers.data?.length ?? 0) > 0 });
  if (!peers.data?.length) return null;
  return (
    <section aria-label={t("peers.title")} className="mb-8 rounded-xl border bg-card p-4">
      <h2 className="mb-3 flex items-center gap-2 text-sm font-semibold"><Server className="size-4" aria-hidden />{t("peers.title")}</h2>
      {status.isPending ? (
        <p className="text-sm text-muted-foreground">{t("common.loading")}</p>
      ) : (
        <ul className="space-y-3">{(status.data ?? []).map((peer) => <Peer key={peer.name} peer={peer} />)}</ul>
      )}
    </section>
  );
}

function Peer({ peer }: { peer: Schemas["PeerSeriesOut"] }) {
  const { t } = useTranslation();
  const [library, setLibrary] = useState<string>(String(peer.libraries[0]?.id ?? ""));
  const missing = peer.books.filter((b) => !b.present);
  const copy = async () => {
    const { error } = await fetchClient.POST("/api/peers/copy", { body: { peer: peer.name, library_id: Number(library), book_ids: missing.map((b) => b.book_id) } });
    if (error) toast.error(errorMessage(error, t("common.errorGeneric")));
    else toast.success(t("peers.queued", { count: missing.length, name: peer.name }));
  };
  if (peer.error) return <li className="text-sm"><span className="font-medium">{peer.name}</span>: <span className="text-destructive">{peer.error}</span></li>;
  return (
    <li className="flex flex-wrap items-center gap-3 text-sm">
      <span className="font-medium">{peer.name}</span>
      <Badge variant="secondary">{t("peers.has", { have: peer.books.length - missing.length, total: peer.books.length })}</Badge>
      {missing.length > 0 && peer.libraries.length > 0 && (
        <span className="ml-auto flex items-center gap-2">
          <Select value={library} onValueChange={(v) => setLibrary(String(v))}>
            <SelectTrigger size="sm" className="w-40" aria-label={t("peers.library")}>
              <SelectValue>{(v: string) => peer.libraries.find((l) => String(l.id) === v)?.name ?? v}</SelectValue>
            </SelectTrigger>
            <SelectContent>
              {peer.libraries.map((l) => <SelectItem key={l.id} value={String(l.id)}>{l.name}</SelectItem>)}
            </SelectContent>
          </Select>
          <Button size="sm" variant="outline" onClick={() => void copy()}>{t("peers.copy", { count: missing.length })}</Button>
        </span>
      )}
    </li>
  );
}
