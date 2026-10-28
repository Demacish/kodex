import { useCallback, useState } from "react";

/** Reader settings remembered in local storage, per key. */
export function usePref<T>(key: string, fallback: T): [T, (value: T) => void] {
  const [value, setValue] = useState<T>(() => {
    try {
      const saved = localStorage.getItem(key);
      return saved == null ? fallback : (JSON.parse(saved) as T);
    } catch {
      return fallback;
    }
  });
  const set = useCallback(
    (next: T) => {
      setValue(next);
      try {
        localStorage.setItem(key, JSON.stringify(next));
      } catch {
        // kept for this visit
      }
    },
    [key],
  );
  return [value, set];
}
