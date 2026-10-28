import { readFileSync } from "node:fs";
import { fileURLToPath, URL } from "node:url";

import tailwindcss from "@tailwindcss/vite";
import { tanstackRouter } from "@tanstack/router-plugin/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";
import { VitePWA } from "vite-plugin-pwa";
import { viteStaticCopy } from "vite-plugin-static-copy";

// In development the API runs separately (uvicorn on :8000, or KODEX_API);
// in production the api serves this build (backend/kodex/core/spa.py).
const { version } = JSON.parse(readFileSync(new URL("./package.json", import.meta.url), "utf8")) as { version: string };

export default defineConfig({
  // The build's version, compared with the server's (src/lib/stale.ts).
  define: { __KODEX_VERSION__: JSON.stringify(version) },
  plugins: [
    tanstackRouter({ target: "react", autoCodeSplitting: true }),
    react(),
    tailwindcss(),
    // An installable app whose shell works offline; covers and pages already
    // seen stay readable, and API answers fall back to the last ones.
    VitePWA({
      registerType: "autoUpdate",
      injectRegister: false,
      includeAssets: ["favicon.svg", "apple-touch-icon.png", "theme.js"],
      manifest: {
        name: "Kodex",
        short_name: "Kodex",
        description: "Comics, manga and e-books from your own server",
        theme_color: "#0c0c0f",
        background_color: "#0c0c0f",
        display: "standalone",
        start_url: "/",
        icons: [
          { src: "/icon-192.png", sizes: "192x192", type: "image/png" },
          { src: "/icon-512.png", sizes: "512x512", type: "image/png" },
          { src: "/icon-maskable-512.png", sizes: "512x512", type: "image/png", purpose: "maskable" },
        ],
      },
      workbox: {
        globPatterns: ["**/*.{js,css,html,svg,png,woff2}"],
        globIgnores: ["**/pdfjs/**"],
        maximumFileSizeToCacheInBytes: 3 * 1024 * 1024,
        navigateFallback: "/index.html",
        navigateFallbackDenylist: [/^\/api\//, /^\/opds/, /^\/kosync/, /^\/federation/, /^\/healthz/],
        runtimeCaching: [
          {
            urlPattern: ({ url }) => /^\/api\/books\/\d+\/cover/.test(url.pathname),
            handler: "StaleWhileRevalidate",
            options: { cacheName: "covers", expiration: { maxEntries: 3000, maxAgeSeconds: 60 * 60 * 24 * 30 } },
          },
          {
            urlPattern: ({ url }) => /^\/api\/books\/\d+\/pages\/\d+/.test(url.pathname),
            handler: "CacheFirst",
            options: { cacheName: "pages", expiration: { maxEntries: 600, maxAgeSeconds: 60 * 60 * 24 * 7 } },
          },
          {
            urlPattern: ({ url }) => url.pathname.startsWith("/pdfjs/"),
            handler: "CacheFirst",
            options: { cacheName: "pdfjs", expiration: { maxEntries: 400 } },
          },
          {
            urlPattern: ({ url, request }) =>
              request.method === "GET" && url.pathname.startsWith("/api/") && !url.pathname.startsWith("/api/auth/") && !/\/(file|pages|cover)/.test(url.pathname),
            handler: "NetworkFirst",
            options: { cacheName: "api", networkTimeoutSeconds: 4, expiration: { maxEntries: 300, maxAgeSeconds: 60 * 60 * 24 * 7 } },
          },
        ],
      },
    }),
    // pdf.js loads character maps, fonts, colour profiles and image decoders on demand.
    viteStaticCopy({
      targets: ["cmaps", "standard_fonts", "wasm", "iccs"].map((dir) => ({
        src: `node_modules/pdfjs-dist/${dir}/*`,
        dest: `pdfjs/${dir}`,
      })),
    }),
  ],
  resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
  server: {
    proxy: {
      "/api": { target: process.env.KODEX_API ?? "http://127.0.0.1:8000", changeOrigin: false },
    },
  },
  build: { target: "es2022", sourcemap: true },
});
