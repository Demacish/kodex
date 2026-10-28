# Running Kodex

## The containers

`docker compose up -d` starts three: `db` (PostgreSQL 18), `api` (the web
client and the API, on port 8000) and `worker` (scans, matching, covers,
downloads, backups). Put a reverse proxy with TLS in front of the api.

- **Who it runs as.** The image starts as root only to become `PUID`:`PGID`
  (1000:1000 unless `.env` says otherwise), gives them its volumes, and then
  runs unprivileged. Use your own `id -u` and `id -g` on a NAS, so the files
  Kodex writes in the libraries are yours. `PUID=0` keeps it root, for
  libraries only root can read. Run with compose's `user:` or rootless
  Podman and it stays that user.
- **Read-only.** The containers' root filesystems are read-only. Kodex
  writes to the volumes (`/data/covers`, `/data/downloads`, `/data/backups`),
  the libraries, and `/tmp`, which is a tmpfs.
- **Health.** `/healthz` answers while the process runs. `/readyz` answers
  once the database is reachable and its schema is at the migrations' head.
  It is what the image's healthcheck uses, and the worker waits for it.
- **Stopping.** `docker compose stop` sends SIGTERM straight to the servers.
  The api finishes the requests in flight (up to 25 s), and the worker the
  job it is running (up to a minute).
- **Secrets from files.** Any setting can come from a file: `NAME_FILE=/run/secrets/name`
  sets `NAME` from the file, for Docker and Podman secrets. Without
  compose's interpolation, give the api `DATABASE_URL_FILE` as well.

## Backups

The worker dumps the database every night at 03:30 into the `backups` volume
and keeps the newest `BACKUP_KEEP` (7). Copy them somewhere else too: a
backup on the same disk doesn't survive the disk.

    docker compose exec api python -m kodex.core.backup dump      # one now
    docker compose exec api python -m kodex.core.backup list
    docker compose exec api python -m kodex.core.backup verify /data/backups/kodex-….dump

`verify` is the restore drill. It restores the dump into a database of its
own, compares the main tables' row counts with the live ones, and drops it.
CI runs it on every change (`tools/smoke-compose.sh`).

The libraries are your files and aren't in the dump. Covers and the page
cache are rebuilt from them.

### Restoring

    docker compose stop worker
    docker compose exec api python -m kodex.core.backup restore /data/backups/kodex-….dump
    docker compose restart api worker

The api migrates the restored schema to head as it starts.

## Upgrading Kodex

Take a dump first (`docker compose exec api python -m kodex.core.backup dump`).
With the published image (`KODEX_IMAGE`, the newest release by default):

    docker compose pull
    docker compose up -d

Built from a checkout instead: `git pull`, then `docker compose up -d --build`.

The api migrates the database before it serves. Migrations only move
forward; to go back, restore the dump taken before the upgrade.

## Upgrading PostgreSQL to a new major version

PostgreSQL can't open another major version's data directory, so the data
goes through a dump:

1. Take a dump and check it:
   `docker compose exec api python -m kodex.core.backup dump`, then `verify`
   it.
2. `docker compose down`.
3. In `docker-compose.yml`, set the new image (`postgres:19`) and a new data
   volume (`db-data-19:/var/lib/postgresql`). Rebuild the api image with the
   matching client: `docker compose build --build-arg POSTGRES_MAJOR=19`.
4. `docker compose up -d db`. Then start the api and restore the dump into
   the new, empty database:
   `docker compose run --rm api python -m kodex.core.backup restore /data/backups/kodex-….dump`.
5. `docker compose up -d`.

Keep the old volume until Kodex has run on the new one for a while.

## Memory

The compose file sets no limits; a small NAS can. At rest, with a few hundred
books, the api uses about 160 MB and the worker about 100 MB. A scan reads
archives in a pool of processes (`SCAN_WORKERS`, one per CPU by default),
and each one adds to the worker's share. Set `SCAN_WORKERS=1` or `2` on a
machine with 2 GB.

With 50 000 books (`.github/workflows/bench.yml`, which makes them up, on two
CPUs), the peaks were:

| | At most | |
| --- | --- | --- |
| A first scan, `SCAN_WORKERS=2`, limited to 2 GB | 241 MB | 6.8 minutes, 124 files a second; with nothing changed, 3.4 seconds |
| The api, limited to 1 GB | 182 MB | |
| PostgreSQL | 594 MB | most of it the page cache, which the kernel takes back when memory is short |

Each peak counts the page cache of the files read, so the whole stack fits
in 2 GB with room to spare. The api's answers with those books, median (95th
percentile):

| | |
| --- | --- |
| A page of 50 books | 124 ms (234 ms) |
| A page of 100 series | 67 ms (109 ms) |
| A series' books | 17 ms (19 ms) |
| Search for "the", which nearly every title has | 404 ms (535 ms) |
| OPDS, newest books | 76 ms (156 ms) |
| Continue reading | 7 ms (8 ms) |
| An app's first sync of the whole catalog | 10 seconds |
