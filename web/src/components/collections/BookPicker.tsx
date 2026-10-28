import { Plus } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { api } from "@/api/client";
import { Cover } from "@/components/library/Cover";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";

/** Finds books by title and picks some. */
export function BookPicker({ onPick, label }: { onPick: (ids: number[]) => Promise<void>; label?: string }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [picked, setPicked] = useState<Map<number, string>>(new Map());
  const [busy, setBusy] = useState(false);
  const hits = api.useQuery("get", "/api/search/books", { params: { query: { q: query.trim(), limit: 24 } } }, { enabled: query.trim().length > 1 });
  const toggle = (id: number, title: string) =>
    setPicked((current) => {
      const next = new Map(current);
      if (next.has(id)) next.delete(id);
      else next.set(id, title);
      return next;
    });
  return (
    <Dialog open={open} onOpenChange={(value) => { setOpen(value); if (!value) setPicked(new Map()); }}>
      <DialogTrigger render={<Button size="sm" />}>
        <Plus aria-hidden />
        {label ?? t("collections.addBooks")}
      </DialogTrigger>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>{label ?? t("collections.addBooks")}</DialogTitle>
        </DialogHeader>
        <Input type="search" value={query} onChange={(e) => setQuery(e.target.value)} placeholder={t("searchPage.placeholder")} aria-label={t("common.search")} autoFocus />
        <ul className="grid max-h-[50dvh] grid-cols-3 gap-3 overflow-y-auto sm:grid-cols-4">
          {(hits.data ?? []).map((hit) => (
            <li key={hit.book_id}>
              <label className="block cursor-pointer">
                <div className="relative">
                  <Cover bookId={hit.book_id} alt="" size="small" />
                  <Checkbox className="absolute top-1.5 left-1.5 bg-background" checked={picked.has(hit.book_id)} onCheckedChange={() => toggle(hit.book_id, hit.title)} aria-label={hit.title} />
                </div>
                <span className="mt-1 line-clamp-2 block text-xs">{hit.title}</span>
              </label>
            </li>
          ))}
        </ul>
        <DialogFooter>
          <span className="mr-auto self-center text-sm text-muted-foreground">{t("list.selected", { count: picked.size })}</span>
          <Button variant="ghost" onClick={() => setOpen(false)}>{t("common.cancel")}</Button>
          <Button
            disabled={picked.size === 0 || busy}
            onClick={async () => {
              setBusy(true);
              try {
                await onPick([...picked.keys()]);
                setOpen(false);
                setPicked(new Map());
              } finally {
                setBusy(false);
              }
            }}
          >
            {t("common.add")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
