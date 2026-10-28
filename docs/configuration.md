# Configuration

Kodex reads its settings from the environment (`.env` with Docker
Compose). Each one can also come from a file: `NAME_FILE=/run/secrets/name`
sets `NAME` from the file's content, for Docker and Podman secrets.
`.env.example` lists every setting with a comment; this page groups the
ones people change.

## The essentials

| Setting | Default | |
| --- | --- | --- |
| `POSTGRES_PASSWORD` | — | The database's password (compose builds `DATABASE_URL` from it). |
| `DATABASE_URL` | built by compose | `postgresql+psycopg://user:password@host:5432/db`, when PostgreSQL runs elsewhere. |
| `LIBRARIES_HOST_PATH` | — | The host folder with the libraries, mounted as `/libraries`. |
| `SORTED_LIBRARY_HOST_PATH` | — | Where the sorting assistant moves sorted files, mounted as `/libraries/_sorterat`. |
| `PUBLIC_APP_URL` | the request's address | The address people use; links, the OIDC redirect and passkeys take it from here. |
| `PUID`, `PGID` | 1000 | Who the server runs as; 0 keeps it root. |
| `SECRET_KEY` | — | Encrypts authenticator secrets and tracker tokens. Never change it once set. |
| `API_PORT` | 8000 | The host port, bound to 127.0.0.1. |
| `FORWARDED_ALLOW_IPS` | 127.0.0.1 | The reverse proxy's address: from it, Kodex trusts `X-Forwarded-For` and `-Proto`. |

## Accounts

| Setting | Default | |
| --- | --- | --- |
| `LOCAL_LOGIN_ENABLED` | true | Kodex's own passwords. False leaves only the provider (and passkeys). |
| `PASSKEYS_ENABLED` | true | Passkeys for logging in and as a second step. |
| `SESSION_DAYS` | 30 | How long a login lasts while unused. |
| `COOKIE_SECURE` | auto | Secure cookies over HTTPS; `true` or `false` forces it. |
| `LOGIN_MAX_FAILURES` | 5 | Failed logins for one username before it waits… |
| `LOGIN_MAX_FAILURES_PER_IP` | 30 | …or from one address… |
| `LOGIN_LOCKOUT_MINUTES` | 15 | …within this long. |

### Logging in through a provider

Any OpenID Connect provider with discovery works: Authentik, Keycloak,
Authelia, Zitadel, Pocket ID and others. Register Kodex with it as a client
with the redirect URI `<PUBLIC_APP_URL>/api/auth/oidc/callback`, then:

| Setting | |
| --- | --- |
| `OIDC_ISSUER` | The provider's issuer URL. Empty: Kodex's own accounts only. |
| `OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET` | The client; no secret for a public client (PKCE). |
| `OIDC_DISPLAY_NAME` | The login button's name ("Logga in med …"). |
| `OIDC_SCOPES` | Default `openid profile email groups`. |
| `OIDC_GROUPS_CLAIM` | The claim with the user's groups (`groups`). |
| `OIDC_REQUIRED_GROUP` | Only its members may log in; empty: everyone the provider lets through. |
| `OIDC_ADMIN_GROUP` | Its members are admins. |
| `OIDC_CREATE_USERS` | Whether a first login creates an account (true), or only accounts linked under Inställningar may log in. |

v1's `AUTHENTIK_*` names for these still work.

## Libraries and scanning

| Setting | Default | |
| --- | --- | --- |
| `SCAN_WORKERS` | one per CPU | Processes reading archives during a scan; 1 on a small NAS. |
| `RESCAN_INTERVAL_MINUTES` | 60 | Libraries are rescanned this often (0: only on demand). |
| `MATCH_AFTER_SCAN` | true | New series are matched with the metadata sources after a scan. |
| `MATCHING_PROVIDERS` | all set up | Which sources the matcher asks, comma-separated. |
| `SORTING_AUTO_APPLY` | true | The sorting assistant moves what it is sure of without asking. |
| `JOB_RETENTION_DAYS` | 14 | Finished jobs are kept this long. |
| `READING_JOURNAL_DAYS` | 90 | The reading journal keeps every report this long, then one per book and day. |

## Metadata sources

MangaDex, AniList, MangaUpdates and Open Library need nothing. The others
need a key:

| Setting | |
| --- | --- |
| `COMICVINE_API_KEY` | Comic Vine (western comics). |
| `METRON_USERNAME`, `METRON_PASSWORD` | Metron (story arcs, cover hashes). |
| `GOOGLE_BOOKS_API_KEY` | Google Books. |
| `HARDCOVER_API_TOKEN` | Hardcover (books). |
| `ENRICHMENT_USER_AGENT` | Contact information sent to the sources; set it to yours. |

## Reading apps and devices

| Setting | Default | |
| --- | --- | --- |
| `KOBO_STORE_PROXY` | true | A Kobo's store requests go on to Kobo; false keeps the device off Kobo's servers. |
| `GUIDED_VIEW_ENABLED` | true | Panel-by-panel reading of comics. |

The keys for KOReader, OPDS apps and Kobo are made per person under
Inställningar; see [clients.md](clients.md).

## Notifications and delivery

| Setting | |
| --- | --- |
| `NTFY_URL`, `NTFY_TOKEN` | The ntfy server for the users' own topics (ntfy.sh by default). |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | New requests and releases, to the admins. |
| `DISCORD_WEBHOOK_URL` | The same, to Discord. |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM_ADDRESS` | Send to Kindle. Kindle only accepts mail from addresses on the user's approved list. |
| `KODEX_PEERS` | Other Kodex servers, as JSON: `[{"name": "Hemma-NAS", "url": "https://…", "upload_key": "…"}]`. |
| `UPLOAD_API_KEY` | The key other servers and scripts upload into the libraries with. |

## Trackers

`SECRET_KEY` first. MangaUpdates and Kitsu need nothing more. AniList and
MyAnimeList need a client registered with them, with the redirect URI
`<PUBLIC_APP_URL>/api/trackers/anilist/callback` (or `…/myanimelist/callback`):
`ANILIST_CLIENT_ID`, `ANILIST_CLIENT_SECRET`, `MYANIMELIST_CLIENT_ID`,
`MYANIMELIST_CLIENT_SECRET`.

## Acquisition (optional, off)

`ACQUIRE_ENABLED`, Prowlarr, qBittorrent, SABnzbd and the path mappings are
in [acquire.md](acquire.md). Mylar3 and Kapowarr (`MYLAR3_*`, `KAPOWARR_*`),
FlareSolverr and Anna's Archive mirrors are for fetching by hand, so far
only through the API (see acquire.md).

## Backups

| Setting | Default | |
| --- | --- | --- |
| `BACKUP_KEEP` | 7 | Nightly database dumps kept in the backups volume; 0: none. |

## AI suggestions (optional)

`AI_PROVIDER` (`openai`, `claude` or `gemini`), `AI_API_KEY` and `AI_MODEL`:
recommendations and generated collections. Off without a key.
