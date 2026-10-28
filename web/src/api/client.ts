/**
 * The typed API client, generated from the backend's OpenAPI document
 * (openapi.json → schema.d.ts, `npm run api`). The web client logs in with
 * a session cookie; unsafe requests echo the CSRF token from the readable
 * `kodex_csrf` cookie (backend: kodex/core/auth/sessions.py).
 */
import createFetchClient, { type Middleware } from "openapi-fetch";
import createClient from "openapi-react-query";

import type { components, paths } from "./schema";

export type Schemas = components["schemas"];

const UNSAFE = new Set(["POST", "PUT", "PATCH", "DELETE"]);

export function csrfToken(): string | undefined {
  const cookie = document.cookie.split("; ").find((c) => c.startsWith("kodex_csrf="));
  return cookie ? decodeURIComponent(cookie.slice("kodex_csrf=".length)) : undefined;
}

let onUnauthorized: (() => void) | undefined;

/** Called when a request answers 401 (the session ended): back to login. */
export function setUnauthorizedHandler(handler: () => void) {
  onUnauthorized = handler;
}

const session: Middleware = {
  onRequest({ request }) {
    const token = UNSAFE.has(request.method) ? csrfToken() : undefined;
    if (token) request.headers.set("X-CSRF-Token", token);
    return request;
  },
  onResponse({ request, response }) {
    if (response.status === 401 && !new URL(request.url).pathname.startsWith("/api/auth/")) onUnauthorized?.();
    return response;
  },
};

export const fetchClient = createFetchClient<paths>({ baseUrl: window.location.origin, credentials: "same-origin" });
fetchClient.use(session);

export const api = createClient(fetchClient);

/** A readable message from an error the API answered with. */
export function errorMessage(error: unknown, fallback: string): string {
  if (error && typeof error === "object" && "detail" in error) {
    const detail = (error as { detail: unknown }).detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail) && detail[0] && typeof detail[0] === "object" && "msg" in detail[0]) {
      return String((detail[0] as { msg: unknown }).msg);
    }
  }
  if (error instanceof Error && error.message) return error.message;
  return fallback;
}

/** The API's own address for a file (covers, pages, downloads). */
export function apiUrl(path: string): string {
  return path.startsWith("/api/") ? path : `/api${path}`;
}
