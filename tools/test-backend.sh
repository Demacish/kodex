#!/usr/bin/env bash
# Runs the backend checks in Docker against a throwaway PostgreSQL 18, the
# same way CI does. Usage: tools/test-backend.sh [pytest args...]
#   KODEX_TEST_CMD="ruff check ." tools/test-backend.sh   # run another command
set -euo pipefail

repo="$(cd "$(dirname "$0")/.." && pwd)"
network=kodex-test
db=kodex-test-pg
image=kodex-backend-test

docker network inspect "$network" >/dev/null 2>&1 || docker network create "$network" >/dev/null
if ! docker container inspect "$db" >/dev/null 2>&1; then
  docker run -d --rm --name "$db" --network "$network" \
    -e POSTGRES_USER=kodex -e POSTGRES_PASSWORD=kodex -e POSTGRES_DB=kodex_test \
    --tmpfs /var/lib/postgresql postgres:18 -c fsync=off -c synchronous_commit=off >/dev/null
fi
until docker exec "$db" pg_isready -U kodex -d kodex_test >/dev/null 2>&1; do sleep 0.5; done

docker build -q --target test -t "$image" "$repo/backend" >/dev/null
docker run --rm --network "$network" \
  -v "$repo:/repo" -w /repo/backend \
  -e PYTHONDONTWRITEBYTECODE=1 \
  -e TEST_DATABASE_URL="postgresql+psycopg://kodex:kodex@$db:5432/kodex_test" \
  "$image" sh -c "${KODEX_TEST_CMD:-python -m pytest -p no:cacheprovider \"\$@\"}" sh "$@"
