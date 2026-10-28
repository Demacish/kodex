# Kodex

Kodex is a self-hosted library server and reader for comics, manga and
e-books. One server keeps your libraries, and you read them in the browser,
in the Kodex Android app, or in the reading apps and e-readers you already
have.

## What it does

- **Libraries** of CBZ, CBR, CB7, EPUB, PDF and folders of images, grouped
  into series. Embedded metadata (ComicInfo.xml, OPF, PDF properties) is
  read, and series are matched against Comic Vine, Metron, MangaDex,
  AniList, MangaUpdates, Open Library, Google Books and Hardcover. The
  match carries a confidence score; the doubtful ones wait in a review
  queue instead of being guessed.
- **Reading** in the browser: comics one page, two pages, continuous or as a
  webtoon strip; EPUB with foliate-js; PDF with pdf.js. The position follows
  you across devices, and a reading journal keeps every report.
- **The Android app** keeps the catalog on the device, downloads books to
  read offline, and sends the positions when it is online again. It reads
  comics, manga, EPUB (with read-aloud) and PDF.
- **Other apps:** OPDS 1.2 with page streaming and OPDS 2.0, KOReader's
  progress sync, and Kobo e-readers syncing their books and positions
  ([docs/clients.md](docs/clients.md)).
- **Collections:** manual, smart (rules evaluated in the database),
  story arcs in reading order, CBL reading lists in and out.
- **Discovery:** full-text and fuzzy search, followed series with a release
  calendar, and requests for what's missing. With the acquisition add-on,
  an approved request for a missing issue downloads and files itself
  ([docs/acquire.md](docs/acquire.md)).
- **Accounts** of Kodex's own, with passkeys and two-step login, or through
  any OpenID Connect provider. There are personal API keys, and roles for
  admins, users and guests.
- **Delivery:** Send to Kindle; notifications to Telegram, Discord and ntfy;
  copying books to another Kodex server.

## Running it

Docker Compose, with PostgreSQL as the only other service:

    git clone https://github.com/Demacish/kodex.git && cd kodex
    cp .env.example .env      # set POSTGRES_PASSWORD and the library paths
    docker compose up -d      # pulls ghcr.io/demacish/kodex (amd64, arm64)

Then open the server in a browser; the first visit creates the admin. The
whole walk-through, with a reverse proxy, is in
[docs/install.md](docs/install.md).

## Documentation

| | |
| --- | --- |
| [Installing](docs/install.md) | Requirements, first start, reverse proxy, libraries |
| [Configuration](docs/configuration.md) | The settings, grouped |
| [Running Kodex](docs/operations.md) | Containers, backups, upgrades, memory |
| [Security](docs/security.md) | What protects accounts and the server |
| [Reading apps and devices](docs/clients.md) | The Android app, KOReader, OPDS apps, Kobo, trackers |
| [Acquisition](docs/acquire.md) | The optional request → download → library flow |
| [Migrating from v1](docs/migrating-from-v1.md) | Moving a Kodex v1 installation over |
| [The API](docs/api.md) | OpenAPI, authentication, delta sync |
| [Why PostgreSQL](docs/why-postgres.md) | And not SQLite |
| [Decisions](docs/decisions/README.md) | Architecture decision records |
| [Contributing](CONTRIBUTING.md) | Development setup, tests, commits |

## Repository layout

| Path | Contents |
| --- | --- |
| `backend/kodex/` | The server, by module: `core`, `library`, `formats`, `matching`, `reading`, `collections`, `discovery`, `acquire`, `delivery`, `jobs` |
| `backend/app/` | v1's models, and the code still on its way into `kodex/` |
| `web/` | The web client (Vite, React), served by the server |
| `androidApp/`, `shared/` | The Android app and its plain-Kotlin core |
| `docs/` | Documentation and decision records |
| `deploy/` | Templates for Portainer, Synology and Unraid |
| `tools/` | Fixture generators, benchmarks, the compose smoke test |

## License

[MIT](LICENSE).
