# 0018. The server is Docker-compatible

Status: Accepted (2026-10-25)

## Context

The maintainer requires the whole server to run in Docker without anything
installed on the host (plan section "Docker‑kompatibel server").

## Decision

One multi-arch image runs the api, the worker and one-off commands, with every
tool it needs inside (unar, bsdtar, libvips, pdfium, kepubify). Configuration
comes from environment variables, with `<NAME>_FILE` for secrets; state lives
only in volumes; it runs as non-root (uid 1000 now, `PUID`/`PGID` in phase 7);
migrations run at start under an advisory lock; `HEALTHCHECK` probes
`/healthz` (and `/readyz` later); logs go to stdout. `docker compose up -d`
with only an `.env` gives a working instance, and CI builds the images and
runs a compose smoke test with Playwright on every push.

## Consequences

Every phase keeps the image and compose file working. Rootless Podman and NAS
templates (Unraid, Synology/Portainer) are verified in phase 7.
