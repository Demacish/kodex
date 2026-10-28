import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";

import { csrfToken, fetchClient, type Schemas } from "@/api/client";

import { deviceId, deviceName, nextSeq } from "./device";

export type Progress = Schemas["ReadingProgressOut"];

export interface ProgressUpdate {
  position: string;
  percent: number;
  finished: boolean;
  chapter?: string | null;
}

const SAVE_DELAY = 1500;
const POLL_EVERY = 30_000;

/**
 * Saves the reader's position (debounced, and right away when the page is
 * hidden) and watches for a newer one from another device, which the
 * reader can offer to jump to.
 */
export function useProgress(bookId: number, initial: Progress | null | undefined, locatorKind: Schemas["ReadingProgressIn"]["locator_kind"]) {
  const queryClient = useQueryClient();
  const pending = useRef<ProgressUpdate | null>(null);
  const timer = useRef<number | undefined>(undefined);
  const lastSaved = useRef<string | null>(initial?.position ?? null);
  const [elsewhere, setElsewhere] = useState<Progress | null>(null);

  const body = (update: ProgressUpdate) => ({
    position: update.position,
    locator_kind: locatorKind ?? null,
    progress_percent: Math.max(0, Math.min(100, update.percent)),
    is_finished: update.finished,
    chapter: update.chapter ?? null,
    device_id: deviceId(),
    device_name: deviceName(),
    client_seq: nextSeq(),
    client_at: new Date().toISOString(),
  });

  const flush = useCallback(
    (keepalive = false) => {
      window.clearTimeout(timer.current);
      const update = pending.current;
      if (!update) return;
      pending.current = null;
      lastSaved.current = update.position;
      if (keepalive) {
        // fetch with keepalive survives the page closing; sendBeacon can't PUT.
        void fetch(`/api/books/${bookId}/progress`, {
          method: "PUT",
          keepalive: true,
          credentials: "same-origin",
          headers: { "Content-Type": "application/json", "X-CSRF-Token": csrfToken() ?? "" },
          body: JSON.stringify(body(update)),
        }).catch(() => undefined);
        return;
      }
      void fetchClient
        .PUT("/api/books/{book_id}/progress", { params: { path: { book_id: bookId } }, body: body(update) })
        .then(({ data }) => {
          if (data) queryClient.setQueryData(["get", "/api/books/{book_id}/progress", { params: { path: { book_id: bookId } } }], data);
        })
        .catch(() => undefined);
    },
    [bookId, queryClient],
  );

  const save = useCallback(
    (update: ProgressUpdate) => {
      pending.current = update;
      setElsewhere(null);
      window.clearTimeout(timer.current);
      timer.current = window.setTimeout(() => flush(), SAVE_DELAY);
    },
    [flush],
  );

  // A position saved by another device since this one last saved.
  const check = useCallback(async () => {
    if (pending.current) return;
    const { data } = await fetchClient.GET("/api/books/{book_id}/progress", { params: { path: { book_id: bookId } } });
    if (data && data.device_id && data.device_id !== deviceId() && data.position !== lastSaved.current) setElsewhere(data);
  }, [bookId]);

  useEffect(() => {
    const onHide = () => {
      if (document.visibilityState === "hidden") flush(true);
      else void check();
    };
    const onLeave = () => flush(true);
    document.addEventListener("visibilitychange", onHide);
    window.addEventListener("pagehide", onLeave);
    const poll = window.setInterval(() => void check(), POLL_EVERY);
    return () => {
      document.removeEventListener("visibilitychange", onHide);
      window.removeEventListener("pagehide", onLeave);
      window.clearInterval(poll);
      flush(true);
      void queryClient.invalidateQueries({ queryKey: ["get", "/api/me/continue-reading"] });
      void queryClient.invalidateQueries({ queryKey: ["get", "/api/books/{book_id}/progress"] });
    };
  }, [check, flush, queryClient]);

  const dismiss = useCallback(() => {
    if (elsewhere) lastSaved.current = elsewhere.position ?? null;
    setElsewhere(null);
  }, [elsewhere]);

  return { save, elsewhere, dismiss, check };
}
