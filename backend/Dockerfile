FROM python:3.14-slim AS base

# CBR decompression (kodex.formats.archive): unar first, bsdtar from
# libarchive as the fallback. Both are open source and in Debian main.
# pg_dump and pg_restore for backups (kodex.core.backup), from the
# PostgreSQL project's repository at the server's major version: a
# pg_dump older than the server refuses to dump it.
ARG POSTGRES_MAJOR=18
RUN apt-get update \
    && apt-get install -y --no-install-recommends unar libarchive-tools ca-certificates curl gnupg \
    && . /etc/os-release \
    && curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc | gpg --dearmor -o /usr/share/keyrings/pgdg.gpg \
    && echo "deb [signed-by=/usr/share/keyrings/pgdg.gpg] https://apt.postgresql.org/pub/repos/apt ${VERSION_CODENAME}-pgdg main" \
       > /etc/apt/sources.list.d/pgdg.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends "postgresql-client-${POSTGRES_MAJOR}" \
    && apt-get purge -y curl gnupg && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

# Test/lint image: `docker build --target test` (see CONTRIBUTING.md).
FROM base AS test
COPY requirements-dev.txt .
RUN pip install -r requirements-dev.txt

# The web client (web/, ADR 0008), built with Node and served by the api.
# It comes in as the "webapp" build context: compose passes it
# (additional_contexts), or `docker build --build-context webapp=web backend`.
# Built on the build machine's own platform: the output is the same for
# every architecture.
FROM --platform=$BUILDPLATFORM node:24-slim AS web
WORKDIR /web
COPY --from=webapp package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY --from=webapp . .
RUN npm run build

# KEPUB for Kobo sync (kodex.formats.kepub): kepubify, MIT, a static
# binary, checked against the release's sha256.
FROM base AS kepubify
ARG TARGETARCH=amd64
RUN case "$TARGETARCH" in \
      amd64) asset=kepubify-linux-64bit; sum=37d7628d26c5c906f607f24b36f781f306075e7073a6fe7820a751bb60431fc5 ;; \
      arm64) asset=kepubify-linux-arm64; sum=5a15b8f6f6a96216c69330601bca29638cfee50f7bf48712795cff88ae2d03a3 ;; \
      *) echo "no kepubify for $TARGETARCH" >&2; exit 1 ;; \
    esac \
    && python -c "import sys, urllib.request; urllib.request.urlretrieve(sys.argv[1], '/kepubify')" \
       "https://github.com/pgaskin/kepubify/releases/download/v4.0.4/$asset" \
    && echo "$sum  /kepubify" | sha256sum -c - \
    && chmod 755 /kepubify

FROM base AS runtime
# Starts as root only to become PUID:PGID (1000:1000 by default) and give
# them /data, then runs unprivileged (kodex.core.entrypoint). /data (covers,
# download staging, backups) and /tmp are the only places it writes besides
# the libraries, so the root filesystem can be read-only. Started as
# another user (compose's `user:`, rootless Podman) it stays that user.
RUN useradd --system --uid 1000 --user-group --home-dir /app --no-create-home kodex \
    && mkdir -p /data/covers /data/downloads /data/backups \
    && chown -R kodex:kodex /data
COPY alembic.ini ./
COPY kodex ./kodex
COPY app ./app
COPY scripts ./scripts
COPY --from=web /web/dist ./web
COPY --from=kepubify /kepubify /usr/local/bin/kepubify

EXPOSE 8000
# Ready: the database answers at the migrations' head (/healthz only says the process is up).
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/readyz', timeout=4)"]
# NAME_FILE secrets, PUID/PGID, then the command by exec (so it gets SIGTERM).
ENTRYPOINT ["python", "-m", "kodex.core.entrypoint"]
# "api" migrates, then serves; "worker" runs the jobs.
CMD ["api"]
