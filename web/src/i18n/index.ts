import i18n from "i18next";
import { initReactI18next } from "react-i18next";

import en from "./en.json";
import sv from "./sv.json";

export const LANGUAGES = ["sv", "en"] as const;
export type Language = (typeof LANGUAGES)[number];
const STORAGE_KEY = "kodex-language";

declare module "i18next" {
  interface CustomTypeOptions {
    resources: { translation: typeof sv };
  }
}

function initial(): Language {
  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved === "sv" || saved === "en") return saved;
  } catch {
    // no storage: follow the browser
  }
  return navigator.languages.some((l) => l.toLowerCase().startsWith("sv")) ? "sv" : "en";
}

export function setLanguage(language: Language) {
  void i18n.changeLanguage(language);
  try {
    localStorage.setItem(STORAGE_KEY, language);
  } catch {
    // private mode: lasts for this visit
  }
}

i18n.on("languageChanged", (language) => {
  document.documentElement.lang = language;
});

void i18n.use(initReactI18next).init({
  resources: { sv: { translation: sv }, en: { translation: en } },
  lng: initial(),
  fallbackLng: "en",
  interpolation: { escapeValue: false },
  returnNull: false,
});

/** Locale-aware formatting that follows the chosen language. */
export const format = {
  date: (value: string | Date | null | undefined, options: Intl.DateTimeFormatOptions = { dateStyle: "medium" }) =>
    value ? new Intl.DateTimeFormat(i18n.language, options).format(new Date(value)) : "",
  number: (value: number, options?: Intl.NumberFormatOptions) => new Intl.NumberFormat(i18n.language, options).format(value),
  relative: (value: string | Date) => {
    const seconds = (new Date(value).getTime() - Date.now()) / 1000;
    const units: [Intl.RelativeTimeFormatUnit, number][] = [
      ["year", 31536000], ["month", 2592000], ["week", 604800], ["day", 86400], ["hour", 3600], ["minute", 60],
    ];
    const rtf = new Intl.RelativeTimeFormat(i18n.language, { numeric: "auto" });
    for (const [unit, size] of units) if (Math.abs(seconds) >= size) return rtf.format(Math.round(seconds / size), unit);
    return rtf.format(Math.round(seconds), "second");
  },
  bytes: (value: number) => {
    const units = ["B", "kB", "MB", "GB", "TB"];
    let size = value;
    let unit = 0;
    while (size >= 1000 && unit < units.length - 1) {
      size /= 1000;
      unit += 1;
    }
    return `${new Intl.NumberFormat(i18n.language, { maximumFractionDigits: unit ? 1 : 0 }).format(size)} ${units[unit]}`;
  },
};

export default i18n;
