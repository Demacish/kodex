# 0008. Vite + React SPA for the web client

Status: Accepted (implemented in phase 3)

## Context

v1 is Next.js 14 with NextAuth 4, which blocks upgrades. The app sits behind a
login, needs no SSR or SEO, and the readers are entirely client-side.

## Decision

Vite 8, React 19, TypeScript, TanStack Router and Query, Tailwind 4, shadcn/ui
(Base UI), PWA. The backend serves the built SPA.

## Consequences

No Node server in production; one container less. The v1 app is retired when
v2 reaches parity.
