#!/usr/bin/env bash
# A development backend for the web client (web/, `npm run dev`): PostgreSQL,
# the api (reloading on changes) and a worker in Docker, on a
# synthetic library made by tools/fixtures/generate_library.py.
#   tools/dev-stack.sh up       # api on http://127.0.0.1:8000
#   tools/dev-stack.sh down     # stop (the database and library are kept)
#   tools/dev-stack.sh reset    # stop and remove the database and library
# Logs in with AUTH_DISABLED unless KODEX_DEV_AUTH=on.
set -euo pipefail

repo="$(cd "$(dirname "$0")/.." && pwd)"
dir="${KODEX_DEV_DIR:-$repo/.dev}"
network=kodex-dev
image=kodex-backend-test
port="${KODEX_DEV_PORT:-8000}"

down() {
  docker rm -f kodex-dev-api kodex-dev-worker kodex-dev-pg >/dev/null 2>&1 || true
}

case "${1:-up}" in
  down) down; exit 0 ;;
  reset) down; docker volume rm kodex-dev-pg >/dev/null 2>&1 || true; rm -rf "$dir"; exit 0 ;;
  up) ;;
  *) echo "usage: $0 up|down|reset" >&2; exit 2 ;;
esac

mkdir -p "$dir/covers"
if [ ! -f "$dir/library/manifest.json" ]; then
  mkdir -p "$dir/library"
  docker run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp -v "$repo/tools:/tools:ro" -v "$dir/library:/out" \
    python:3.14-slim sh -c "python -m venv /tmp/venv && /tmp/venv/bin/pip install -q Pillow==13.0.0 \
      && /tmp/venv/bin/python -I /tools/fixtures/generate_library.py --out /out --files ${KODEX_DEV_FILES:-150} --pages 8"
fi

docker build -q --target test -t "$image" "$repo/backend" >/dev/null
docker network inspect "$network" >/dev/null 2>&1 || docker network create "$network" >/dev/null
down
docker run -d --name kodex-dev-pg --network "$network" -e POSTGRES_USER=kodex -e POSTGRES_PASSWORD=kodex \
  -e POSTGRES_DB=kodex -v kodex-dev-pg:/var/lib/postgresql postgres:18 >/dev/null
until docker exec kodex-dev-pg pg_isready -U kodex -d kodex >/dev/null 2>&1; do sleep 0.5; done

env=(-e DATABASE_URL=postgresql+psycopg://kodex:kodex@kodex-dev-pg:5432/kodex
     -e LIBRARIES_ROOT=/libraries -e COVERS_DIR=/data/covers -e WEB_DIST_DIR=/repo/web/dist
     -e AUTH_DISABLED="$([ "${KODEX_DEV_AUTH:-off}" = on ] && echo false || echo true)"
     -e PYTHONDONTWRITEBYTECODE=1)
mounts=(-v "$repo:/repo" -v "$dir/library:/libraries" -v "$dir/covers:/data/covers")
docker run -d --name kodex-dev-api --network "$network" -p "127.0.0.1:$port:8000" "${env[@]}" "${mounts[@]}" \
  -w /repo/backend "$image" sh -c "python -m kodex.core.migrate && exec uvicorn app.main:app --host 0.0.0.0 \
    --port 8000 --reload --reload-dir app --reload-dir kodex" >/dev/null
until curl -fsS "http://127.0.0.1:$port/healthz" >/dev/null 2>&1; do sleep 1; done
docker run -d --name kodex-dev-worker --network "$network" "${env[@]}" "${mounts[@]}" -w /repo/backend "$image" \
  python -m app.workers.worker >/dev/null
echo "api on http://127.0.0.1:$port (library in $dir/library); web: cd web && npm run dev"
