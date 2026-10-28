# Installing Kodex

## What you need

- A machine with Docker and Docker Compose v2: a Linux server, a NAS that
  runs containers, or a small single-board computer. amd64 and arm64 both
  work.
- 2 GB of memory is enough; see [Memory](operations.md#memory).
- Your books in folders the machine can read. Kodex doesn't need them
  sorted any particular way, but one folder per series makes the grouping
  certain.
- A domain name and a reverse proxy with TLS, if you'll read from outside
  your network. Passkeys, the Android app's login through the browser and
  Kobo sync need HTTPS.

## 1. Get Kodex

    git clone https://github.com/Demacish/kodex.git
    cd kodex
    cp .env.example .env

The clone gives you the compose file and `.env.example`; the server itself
comes as a published image (`ghcr.io/demacish/kodex`, for amd64 and arm64).

## 2. Fill in `.env`

The three settings you must set:

| Setting | What it is |
| --- | --- |
| `POSTGRES_PASSWORD` | A long random password for the database (`openssl rand -base64 32`). |
| `LIBRARIES_HOST_PATH` | The folder on the host that holds your libraries, mounted as `/libraries`. |
| `SORTED_LIBRARY_HOST_PATH` | A separate, empty folder, where the sorting assistant puts what it sorts. |

And the ones you'll usually want:

| Setting | What it is |
| --- | --- |
| `PUBLIC_APP_URL` | The address people use, e.g. `https://kodex.example.org`. It appears in links, the OpenID Connect redirect and passkeys. |
| `PUID`, `PGID` | Who Kodex runs as: your user's `id -u` and `id -g`, so the files it writes are yours. |
| `SECRET_KEY` | Encrypts the authenticator secrets and tracker tokens. Generate it once and keep it. |
| `FORWARDED_ALLOW_IPS` | Your reverse proxy's address, so Kodex sees the clients' real addresses. |

Everything else is in [configuration.md](configuration.md), and commented in
`.env.example`.

## 3. Start it

    docker compose up -d

The first start pulls the image and creates the database; then the api
container migrates it. (To build the image from the checkout instead, which
takes a while and much more memory than running it, add `--build`.) `docker compose ps` shows all three containers as
healthy when it is done.

The api listens on `127.0.0.1:8000` (`API_PORT` changes the port). Open it
in a browser (through the reverse proxy, or with an SSH tunnel). **The
first visit creates the admin account**; choose its username and password
there.

## 4. Add the libraries

Under Admin › Bibliotek, add one library per kind of book, with:

- a name;
- a path inside `/libraries`, e.g. `serier` for `LIBRARIES_HOST_PATH/serier`;
- a type: comics, manga, e-books, or mixed. The first mixed library is the
  sorting assistant's intake: it sorts new files from there into the
  others.

A scan starts right away and repeats every hour (`RESCAN_INTERVAL_MINUTES`),
which a network share needs. New series are matched with the metadata
sources. Those that need a key (Comic Vine, Metron, Google Books,
Hardcover) are used once their key is in `.env`. Series the matcher isn't
sure of wait under Admin › Granskning.

## 5. A reverse proxy

Caddy:

    kodex.example.org {
        reverse_proxy 127.0.0.1:8000
        request_body {
            max_size 600MB
        }
    }

nginx:

    server {
        listen 443 ssl;
        server_name kodex.example.org;
        # ssl_certificate …;
        client_max_body_size 600m;            # uploads (500 MB)
        large_client_header_buffers 4 32k;    # Kobo sync's headers
        add_header Strict-Transport-Security "max-age=31536000" always;
        location / {
            proxy_pass http://127.0.0.1:8000;
            proxy_set_header Host $host;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
        }
    }

Then set `PUBLIC_APP_URL=https://kodex.example.org`, and
`FORWARDED_ALLOW_IPS` to the proxy's address (with the proxy on the same
host: the Docker bridge's gateway, often `172.17.0.1`, or `*` when nothing
else can reach port 8000).

## 6. People

Under Admin › Användare, create accounts, or let people in through an
OpenID Connect provider (Authentik, Keycloak, Authelia, Zitadel, Pocket ID,
…): see [Logging in through a provider](configuration.md#logging-in-through-a-provider).
Each person sets up passkeys and two-step login under Inställningar.

## On a NAS

- **Synology (Container Manager) and Portainer:**
  [`deploy/portainer/docker-compose.yml`](../deploy/portainer/docker-compose.yml)
  needs no checkout; how to add it is at its top. Point
  `LIBRARIES_HOST_PATH` at the shared folder with your books (e.g.
  `/volume1/books`), and set `PUID`/`PGID` to the user that owns it.
- **Unraid:** Kodex is three containers. Either use the Compose Manager
  plugin with `docker-compose.yml`, or add a PostgreSQL 18 container
  (database and user `kodex`) and then Kodex's two templates,
  [`deploy/unraid/kodex.xml`](../deploy/unraid/kodex.xml) and
  [`kodex-worker.xml`](../deploy/unraid/kodex-worker.xml), with the same
  paths, `DATABASE_URL` and `SECRET_KEY` in both. Copy them to
  `/boot/config/plugins/dockerMan/templates-user/` on the flash drive as
  `my-kodex.xml` and `my-kodex-worker.xml`; they are then under Docker ›
  Add Container › Template.

  CI checks both kinds of template against `docker-compose.yml`, but they
  haven't been tried on a real Synology or Unraid yet: report what you find.
- **Rootless Podman:** CI runs the image under rootless Podman in a pod
  with PostgreSQL, read-only and with no-new-privileges, as the compose
  file does. There, set `PUID=0` and `PGID=0`: root in a rootless
  container is your own user on the host, so Kodex reads and writes your
  library as you, with no rights you don't have. (Any other `PUID` is
  one of your subordinate ids, which can't write to your folders.)
  `podman compose` with `docker-compose.yml` should work the same way but
  isn't tested in CI; report what you find.

## Next

- [Reading apps and devices](clients.md): the Android app, KOReader, OPDS
  apps, a Kobo.
- [Running Kodex](operations.md): backups, upgrades, health checks.
