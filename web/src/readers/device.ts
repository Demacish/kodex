/**
 * This browser as a reading device (backend: kodex/reading/journal.py): a
 * random id kept in local storage, a readable name, and a counter that
 * orders this device's reports.
 */
const ID_KEY = "kodex-device-id";
const SEQ_KEY = "kodex-device-seq";

function storage(): Storage | null {
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

let memoryId: string | undefined;
let memorySeq = 0;

export function deviceId(): string {
  const store = storage();
  const saved = store?.getItem(ID_KEY);
  if (saved) return saved;
  const id = memoryId ?? `web-${crypto.randomUUID()}`;
  memoryId = id;
  store?.setItem(ID_KEY, id);
  return id;
}

export function nextSeq(): number {
  const store = storage();
  const current = Number(store?.getItem(SEQ_KEY) ?? memorySeq) || 0;
  const next = Math.max(current, memorySeq) + 1;
  memorySeq = next;
  store?.setItem(SEQ_KEY, String(next));
  return next;
}

export function deviceName(): string {
  const ua = navigator.userAgent;
  const browser = /Edg\//.test(ua) ? "Edge" : /Firefox\//.test(ua) ? "Firefox" : /Chrome\//.test(ua) ? "Chrome" : /Safari\//.test(ua) ? "Safari" : "Browser";
  const os = /Android/.test(ua) ? "Android" : /iPhone|iPad/.test(ua) ? "iOS" : /Mac OS X/.test(ua) ? "macOS" : /Windows/.test(ua) ? "Windows" : /Linux/.test(ua) ? "Linux" : "";
  return os ? `${browser}, ${os}` : browser;
}
