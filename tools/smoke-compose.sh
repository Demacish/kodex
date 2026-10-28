#!/usr/bin/env bash
# Builds and starts the whole compose stack on a synthetic library, then runs
# the browser tests (web/e2e, phase 3's gate) against it: the first admin,
# libraries and scans through the web client, the review queue (fed by the
# metadata sources that need no keys, over the network), every reader,
# progress between two browsers, and the CSP. Tears it all down. It needs a
# few GB of memory: run it in CI, not on a small shared machine.
#   tools/smoke-compose.sh                    # local: Playwright runs in Docker
#   PLAYWRIGHT=host tools/smoke-compose.sh    # CI: Playwright installed on the host
set -euo pipefail

repo="$(cd "$(dirname "$0")/.." && pwd)"
project=kodex-smoke
api_port="${SMOKE_API_PORT:-28000}"
work="$(mktemp -d)"
compose=(docker compose -p "$project" -f "$repo/docker-compose.yml" --env-file "$work/.env")

cleanup() {
  status=$?
  if [ "$status" -ne 0 ]; then
    # Every server error in full, then the last lines of each service. Each service on its
    # own and without the access log and libvips' chatter, which otherwise fill the lines
    # after a traceback before its exception is reached.
    for service in api worker; do
      "${compose[@]}" logs --no-color "$service" 2>/dev/null | grep -v -E '\| INFO: |INFO:pyvips' \
        | grep -B 3 -A 300 "Traceback" | grep -v -E '^\S+ +\|   +(\^+|~+)$' | head -600 || true
    done
    # And which requests failed.
    "${compose[@]}" logs --no-color api 2>/dev/null | grep -E '" 5[0-9][0-9] ' | head -40 || true
    "${compose[@]}" logs --tail=80 api worker || true
  fi
  "${compose[@]}" down -v --remove-orphans >/dev/null 2>&1 || true
  # Files the api wrote (the uploaded book) belong to its uid 1000.
  docker run --rm -v "$work:/work" python:3.14-slim rm -rf /work/libraries /work/sorted >/dev/null 2>&1 || true
  rm -rf "$work" || true
  exit "$status"
}
trap cleanup EXIT

mkdir -p "$work/libraries" "$work/sorted"
# As the calling user, so the files can be cleaned up afterwards.
docker run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp -v "$repo/tools:/tools:ro" -v "$work/libraries:/out" \
  python:3.14-slim sh -c "python -m venv /tmp/venv && /tmp/venv/bin/pip install -q Pillow==13.0.0 \
    && /tmp/venv/bin/python -I /tools/fixtures/generate_library.py --out /out --files 60 --pages 8"
# The api runs as uid 1000, and the tests upload into the library.
chmod -R a+rwX "$work/libraries" "$work/sorted"

secret() { head -c 24 /dev/urandom | od -An -tx1 | tr -d ' \n'; }
# As docs/install.md has it: .env.example with the settings one must fill in.
cp "$repo/.env.example" "$work/.env"
set_env() {
  grep -v "^$1=" "$work/.env" > "$work/.env.new" || true
  printf '%s=%s\n' "$1" "$2" >> "$work/.env.new"
  mv "$work/.env.new" "$work/.env"
}
set_env POSTGRES_PASSWORD "$(secret)"
set_env LIBRARIES_HOST_PATH "$work/libraries"
set_env SORTED_LIBRARY_HOST_PATH "$work/sorted"
set_env SECRET_KEY "$(secret)"
# And what the test needs: its own port, the env file outside the repo, and
# only the metadata sources that need no key.
set_env API_PORT "$api_port"
set_env KODEX_IMAGE kodex-smoke:local
set_env KODEX_ENV_FILE "$work/.env"
set_env MATCHING_PROVIDERS mangadex,anilist,mangaupdates,open_library

"${compose[@]}" up -d --build --wait --wait-timeout 600

url="http://localhost:$api_port"
# The api serves the web client: a page load gets index.html with its CSP.
curl -fsS -H "Sec-Fetch-Dest: document" "$url/" | grep -q '<div id="root">'
curl -fsSI -H "Sec-Fetch-Dest: document" "$url/" | grep -qi "content-security-policy: default-src 'self'"

if [ "${PLAYWRIGHT:-docker}" = host ]; then
  (cd "$repo/web" && KODEX_WEB_URL="$url" npx playwright test)
else
  docker run --rm --network host -v "$repo/web:/work" -w /work \
    -e KODEX_WEB_URL="$url" mcr.microsoft.com/playwright:v1.64.1-noble \
    sh -c "npx playwright test"
fi

# Phase 7: the server is ready, secrets come from files, and a backup
# restores (the restore drill, kodex.core.backup verify).
curl -fsS "$url/readyz" | grep -q '"ready"'
"${compose[@]}" exec -T api sh -c 'printf "from-a-file\n" > /tmp/secret && SMTP_PASSWORD= SMTP_PASSWORD_FILE=/tmp/secret python -c "from kodex.core.entrypoint import load_file_secrets; import os; load_file_secrets(); assert os.environ[\"SMTP_PASSWORD\"] == \"from-a-file\""'
# The server itself (process 1) runs as PUID; `exec` starts as root.
test "$("${compose[@]}" exec -T api stat -c %u /proc/1)" = 1000
dump=$("${compose[@]}" exec -T api python -m kodex.core.backup dump | tail -n 1)
"${compose[@]}" exec -T api python -m kodex.core.backup verify "$dump"
