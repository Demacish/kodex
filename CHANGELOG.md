# Changelog

All notable changes to Kodex are listed here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and versions follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- A server with accounts but no admin who can log in (one adopted from
  v1, whose users only logged in through Authentik) is set up on its first
  page too: with the setup code the api writes to its log, a username and
  a new password. An existing account keeps everything it had. The Android
  app says when a server isn't set up yet, and opens it in the browser.

### Fixed

- The api waits up to two minutes for the database before migrating, so
  it no longer exits when it starts first.

## [2.0.0] - 2026-10-28

The v2 rebuild: phase 0 (foundations), phase 1 (matching engine), phase 2
(formats, libraries, jobs), phase 3 (the web client), phase 4 (reading,
collections, OPDS and Kobo), phase 5 (the Android app), phase 6
(acquisition and delivery) and phase 7 (hardening).

### Changed

- The server runs on Python 3.14 with FastAPI 0.162, SQLAlchemy 2.1,
  Pydantic 2.14 and psycopg 3.
- The database schema is managed by Alembic. Existing v1 databases are
  adopted automatically on first start (`python -m kodex.core.migrate`),
  including the columns v1 added on its own and the differences left by
  hand-run migrations. Kodex requires PostgreSQL; SQLite is no longer
  supported.
- PDF metadata, PDF text and the Send-to-Kindle conversion use pikepdf and
  pypdfium2 instead of PyMuPDF. JPEG pages are embedded unchanged when a
  comic is sent to a Kindle.
- CBR archives are read with rarfile, decompressed by `unar` or `bsdtar`;
  the proprietary `unrar` is no longer needed.
- Bearer tokens are verified with joserfc instead of python-jose.
- The server image starts as root only to give `/data` to `PUID`:`PGID`
  (1000 by default; 0 keeps root), then runs as that user. Its healthcheck
  is `/readyz`: the database answers and its schema is current. The worker
  waits for the api to be healthy.
- A new web client (`web/`, Vite, React, TanStack Router and Query,
  Tailwind, shadcn/ui) replaces the Next.js app, and the api serves it, so
  the stack is db, api and worker. `NEXTAUTH_*`, `WEB_PORT` and
  `PUBLIC_BACKEND_URL` are gone.
- Kodex handles logins itself and needs no identity provider. The first
  visit to a server without users creates the admin. OpenID Connect is
  optional and works with any provider (Authentik, Keycloak, Authelia,
  ...); it keeps v1's users by their subject. Its settings are now
  `OIDC_*` (v1's `AUTHENTIK_*` names still work), and there is no default
  required group: set `OIDC_REQUIRED_GROUP` and `OIDC_ADMIN_GROUP` to keep
  v1's. The provider must allow `<server>/api/auth/oidc/callback`, and
  `OIDC_CLIENT_SECRET` moves to the api. A provider login no longer
  renames the Kodex account. `python -m kodex.core.auth.cli set-password`
  sets a password from the command line.
- Search runs in PostgreSQL (titles, series, authors, typos, CJK titles,
  summaries and book text), and so do smart collections: Meilisearch, its
  container and the `MEILISEARCH_*` settings are gone.
- The API is under `/api`, described by `/api/openapi.json` (docs at
  `/api/docs`); v1's paths still answer for the Android app.

### Added

- MIT license.
- Backups: a nightly `pg_dump` into the backups volume (`BACKUP_KEEP`, 7),
  and `python -m kodex.core.backup dump|list|verify|restore`. `verify`
  restores the newest dump into a scratch database and compares it with
  the live one. docs/operations.md has restores and PostgreSQL upgrades.
- Every setting can come from a file, `NAME_FILE=/run/secrets/name`, for
  Docker and Podman secrets.
- The containers run with a read-only root filesystem and
  no-new-privileges, and stop cleanly on SIGTERM, giving running requests
  25 seconds. The image builds for amd64 and arm64, and runs under
  rootless Podman.
- The image is published at `ghcr.io/demacish/kodex` for amd64 and arm64,
  and the compose file pulls it (it builds the image only with `--build`,
  or when none is published). Templates for Portainer, Synology and Unraid
  are in `deploy/`.
- English documentation: installing, configuration, running Kodex,
  security, migrating from v1, the API, and why PostgreSQL.
- Accessibility checks (axe, WCAG 2.1 AA) in the end-to-end tests.
- A new Android app (`androidApp/`, minSdk 28), built and tested in CI.
  It logs in with a password, a code for two-step login, or through the
  browser for passkeys and the identity provider. The app gets a key of
  its own, which can be revoked under Inställningar. The catalog is kept on
  the device and synced in deltas (`GET /api/sync/changes`). Books download
  in the background with a notification, on Wi-Fi only if you choose, resume
  where they stopped, and are checked against the server's SHA-256
  (`GET /api/books/{id}/digest`). The next books in a series being read can
  download on their own. Downloaded books read offline:
  - comics and manga left to right or right to left, two pages side by side,
    wide pages in halves, or as a vertical strip, with zoom, tap zones and
    colour filters, and the next book in the series after the last page;
  - EPUB with Readium, including reading aloud;
  - PDF with androidx.pdf.

  Reading positions go to the server when there is a network. A home-screen
  widget shows the book read last. The app is in Swedish and English.
- Acquisition, an add-on that is off by default (`ACQUIRE_ENABLED`,
  docs/acquire.md). A series' missing numbers can be requested from its
  page. With the add-on on, approving such a request is all it takes: Kodex
  finds the issue in Prowlarr, downloads it with qBittorrent or SABnzbd,
  moves it into the series' folder, scans and matches it, fulfils the
  request and tells the person who asked.
- Trackers: reading in any client goes to the reader's lists at
  MangaUpdates, Kitsu, AniList and MyAnimeList, every quarter of an hour and
  only forward. Accounts connect under Inställningar, and series are linked
  under Spåra, suggested from the matcher's external ids. Tokens are
  encrypted with the new `SECRET_KEY`. AniList and MyAnimeList need a client
  registered by the admin (`ANILIST_*`, `MYANIMELIST_*`).
- `shared/`, the plain-Kotlin part of the app. It holds the API client, held
  to `web/openapi.json` by a contract test, delta sync, the outbox of
  reading positions, and the reader's page rules: the same layout as the web
  client and the server's page order.
- OPDS 1.2 with page streaming (OPDS-PSE) and OPDS 2.0 with the Progression
  draft, at `/opds` and `/opds/v2`: reading now, newest, followed series,
  libraries and series in pages, and search. Covers and streamed pages are
  JPEG. The page a PSE app is on becomes the reading position.
- Kobo sync at `/kobo/<key>`: a Kobo e-reader gets the EPUBs of a
  collection as KEPUB (kepubify is in the image), and reading positions go
  both ways; store purchases keep syncing through Kobo's store
  (`KOBO_STORE_PROXY`). Setup for KOReader, OPDS apps and Kobo is in
  docs/clients.md.
- Reading positions say what kind of locator they are, and KOReader,
  Kobo, OPDS apps and the web reader all report into the reading journal,
  where the newest position wins (KOSync used to keep the furthest one).
  Old journal entries are thinned to one a day after
  `READING_JOURNAL_DAYS` (90).
- A Statistik page: books finished per month, the days you read, streaks
  and pages.
- Smart collections can match what you read: unread, reading or finished,
  followed series, and the next unread book of each series; and on title,
  series, publisher and year. Rules can be negated (`not`).
- Reading lists in and out as CBL files: a collection exports in its order
  with Comic Vine ids, and an imported list becomes a collection of the
  books that are here, with the ones that are missing. A manual
  collection's order can be dragged.
- Passkeys: log in without a password, or use one as the second step.
- Two-step login with an authenticator app, with ten one-time recovery
  codes. Admins can reset a user's two-step login and passkeys, also from
  the command line (`reset-two-factor`).
- One-time sign-in links an admin makes for a user, who chooses their own
  password; this is how v1's Authentik-only users get one.
- Linking a Kodex account to the OpenID Connect provider, and unlinking it;
  `OIDC_CREATE_USERS=false` lets in only linked accounts.
- Matching engine (`kodex.matching`). Books are grouped into series from
  file and folder names and embedded metadata without any network access;
  a changed grouping becomes a proposal in the review queue instead of a
  silent move, and moved files keep their identity through their content
  hash. Series are then matched against Comic Vine, Metron, MangaDex,
  AniList, MangaUpdates, Open Library, Google Books and Hardcover: ids
  already in the files are used first, otherwise candidates are scored on
  title, issue coverage, year, publisher, page counts and covers (pHash).
  Only clear matches backed by at least two independent signals are
  applied automatically; everything else goes to the review queue.
  Thresholds and weights live in `matching.toml`.
- Review queue (Admin → Granskning) with candidates, manual search, "no
  match", regroup proposals, bulk actions and undo for every decision.
  Series can be split and merged, and books moved between series; fields a
  person has set are locked against automatic changes.
- E-books are identified by an ISBN in the book first: in the OPF, or, for
  a PDF, printed on its first pages. A PDF's own title and authors are read
  from its document properties, leaving out what authoring tools leave
  behind there. File names with the words run together
  (`riversandriverboats.pdf`) count as the title they spell.
- Manga numbered by volume are compared with the volumes a series'
  chapters are collected in at MangaDex.
- Collected editions are matched to collected runs: a comic without a
  number and with more than 100 pages counts as one, a thick "Book 2" is
  volume 2, and a volume's own title ("Harbour Watch v00 - Stormfront!") and named
  editions ("Compendium", "Omnibus") are searched too. Their covers are
  compared as well, also when the trade dress differs from the issue
  cover the artwork comes from (OpenCV keypoint matching), and a run with
  the very same cover is preferred over one that only shares the artwork.
- A content id per book, a hash over its pages that writing metadata into
  the file or converting a CBR to a CBZ doesn't change; moved and converted
  files keep their book (progress, collections) by it. Every KOReader
  document id a file has had stays mapped to its book, so devices holding
  an older copy keep syncing.
- Duplicates: books with the same pages are marked as copies of the
  oldest one after every scan, and books with the same number and nearly
  the same cover in different files are listed for review
  (`GET /library/duplicates`).
- Libraries can be read-only (no uploads, sorting moves, write-back or
  conversions) and can opt in to write-back: ComicInfo.xml into CBZ files
  (merged with the existing one, pages untouched, so a book keeps its
  identity, duplicates and KOReader sync) and series.json in Mylar3's
  format alongside Kodex's own backup (`POST
  /library/libraries/{id}/write-back`). A CBR or CB7 can be converted to
  CBZ (`POST /library/books/{id}/convert`); the original stays until it is
  deleted and shows as a duplicate meanwhile.
- Covers in three sizes (200, 400 and 1000 px, WebP), made with pyvips by
  a job after each scan from the downloaded cover or the book's own (an
  archive's front cover, an EPUB's cover image, a PDF's first page):
  `GET /books/{id}/cover?size=small|medium|large` (`thumb=true` is
  medium). A new cover or a changed file makes them again.
- Background jobs run on Procrastinate in PostgreSQL; Redis is no longer
  part of the stack. Periodic jobs (library polling for network shares,
  the weekly release check, a nightly cleanup of ended jobs) are
  deduplicated in the database however many workers run, replacing the
  scheduler thread in the api process. A job's result or error is kept for
  the admin job view (`JOB_RETENTION_DAYS`).
- Faster scans: the library's books are loaded in one query, so an
  unchanged file costs a stat, and new or changed files are read in a
  process pool (`SCAN_WORKERS`, default one per CPU). On a 2-core machine
  50 000 files scan at about 125 files/s and an unchanged rescan takes a
  few seconds. A file that fails to read no longer undoes the rest of the
  scan. Measure with `tools/bench/scan.py`.
- CB7 (7z) comics. Archives are recognised by their content, so a ".cbr"
  that is really a zip opens.
- Archive reading is bounded: entries that would unpack beyond 256 MiB or
  compress suspiciously well, and archives with more than 20 000 entries,
  are refused, and no entry is ever written under its own name.
- Translated and reprint editions (recognised by publisher, configurable
  in `matching.toml`) give way to the original in the files' language.
- Provider clients share a response cache and rate limits stored in the
  database, so several workers respect the same budget.
- File-name parser with a golden corpus, and an evaluation
  (`python -m kodex.matching.eval`) over a synthetic corpus of 624 cases in
  thirteen strata that runs as a CI gate.
- Synthetic test-library generator and pinned public-domain test EPUBs.
- CI for backend, web and a full Docker Compose smoke test.
- The web client, in Swedish and English, light or dark: home shelves,
  libraries, series (with what to read next and gaps in the numbering),
  books, search in titles and in the text, following, the release
  calendar, suggestions, collections and story arcs, requests and
  settings; for admins the review queue first, then libraries, jobs,
  import, duplicates, flagged pages, missing files, users, integrations
  and statistics. It installs as an app and its shell works offline.
- Readers: comics and manga page by page, as spreads, continuous or as a
  webtoon, right to left, with filters, trimmed margins, keys, taps and
  swipes; PDF with pdf.js; EPUB with foliate-js, with search in the book.
  Pages come as WebP at the screen's width (`?max_width=`, `?trim=true`).
- A reading journal: every position each device reports is kept, the
  newest wins, and a reader offers a newer position from another device.
- Personal API keys for apps, OPDS readers, KOReader sync and Kobo,
  shown once; roles (admin, user, guest); user management; throttled
  password logins.
- `MATCHING_PROVIDERS` picks the metadata sources.
- The page is sent with a Content Security Policy, so scripts in books
  don't run.

### Security

- Authenticator secrets are encrypted at rest with `SECRET_KEY`; those
  already stored are encrypted by the next migration.
- Cover and metadata fetches refuse addresses on the server's own machine
  and network, also after a redirect (SSRF).
- Uploads are written to disk as they arrive, not held in memory.
- Responses carry `X-Content-Type-Options`, `Referrer-Policy` and
  `X-Frame-Options`.

### Fixed

- A page of a library's series no longer builds every series in the
  library: with 50 000 books it took 375 ms, now 67 ms.

- Pages are in natural order ("2.jpg" before "10.jpg"), and two pages with
  the same file name in different folders of an archive no longer show as
  the same page.
- A library's path must lie inside the libraries root.
- A skipped item in the review queue can be undone.
- Uploading into a library folder the server may not write to says so
  (409) instead of failing with a server error.
- Automatic enrichment no longer changes which Comic Vine issue a book is
  linked to for a series the matching engine has matched; it only fills in
  missing details.

[Unreleased]: https://github.com/Demacish/kodex/compare/v2.0.0...HEAD
[2.0.0]: https://github.com/Demacish/kodex/releases/tag/v2.0.0
