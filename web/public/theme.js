// The theme before the first paint (src/lib/theme.tsx keeps it after that).
// A file, not inline, so the page's CSP can forbid inline scripts.
try {
  const theme = localStorage.getItem("kodex-theme") ?? "system";
  const dark = theme === "dark" || (theme === "system" && matchMedia("(prefers-color-scheme: dark)").matches);
  document.documentElement.classList.toggle("dark", dark);
} catch {}
