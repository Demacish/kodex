#!/usr/bin/env bash
# Regenerates the API contract and the web client's types from it (ADR 0013):
# web/openapi.json from the backend, then web/src/api/schema.d.ts.
set -euo pipefail
repo="$(cd "$(dirname "$0")/.." && pwd)"
docker build -q --target test -t kodex-backend-test "$repo/backend" >/dev/null
docker run --rm -v "$repo:/repo" -w /repo/backend -e PYTHONDONTWRITEBYTECODE=1 kodex-backend-test \
  python -m kodex.core.openapi /repo/web/openapi.json
(cd "$repo/web" && npm run --silent api)
