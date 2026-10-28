# Architecture decision records

One file per decision in the plan's stack table ("Val av stack"), plus later ones. A decision changes by adding a new record that supersedes the old one.

| ADR | Decision | Status |
| --- | --- | --- |
| [0001](0001-license.md) | MIT license | Accepted (2026-10-25) |
| [0002](0002-backend-language.md) | Python and FastAPI for the backend | Accepted |
| [0003](0003-orm-and-migrations.md) | SQLAlchemy 2.1, Alembic and Pydantic 2 | Accepted |
| [0004](0004-data-store.md) | PostgreSQL as the only data store | Accepted |
| [0005](0005-search.md) | PostgreSQL full-text and trigram search | Accepted (implemented in phase 4, 2026-10-26) |
| [0006](0006-jobs.md) | Procrastinate for background jobs | Accepted (implemented in phase 2) |
| [0007](0007-auth.md) | The backend owns authentication | Accepted (implemented in phase 3) |
| [0008](0008-web-client.md) | Vite + React SPA for the web client | Accepted (implemented in phase 3) |
| [0009](0009-epub-reader-web.md) | EPUB reader for the web | Superseded by 0019 |
| [0010](0010-pdf-and-image-reader-web.md) | pdf.js and our own image reader on the web | Accepted (implemented in phase 3) |
| [0011](0011-android.md) | Kotlin and Compose with a shared KMP module | Accepted; partly superseded by 0021 |
| [0012](0012-pdf-android.md) | androidx.pdf with a Pdfium fallback on Android | Superseded by 0022 |
| [0013](0013-api-contract.md) | OpenAPI 3.1 as the API contract | Accepted (implemented in phase 3) |
| [0014](0014-opds-and-kobo.md) | Own OPDS 1.2/2.0 and Kobo sync implementations | Accepted (implemented in phase 4) |
| [0015](0015-image-processing.md) | pyvips for images, pypdfium2 for PDF pages | Accepted (implemented in phase 2) |
| [0016](0016-archives.md) | rarfile with unar/bsdtar, py7zr and puremagic | Accepted |
| [0017](0017-distribution.md) | Docker Compose as the distribution | Accepted |
| [0018](0018-docker-compatible-server.md) | The server is Docker-compatible | Accepted (2026-10-25) |
| [0019](0019-epub-reader-foliate.md) | foliate-js for EPUB on the web | Accepted (2026-10-26) |
| [0020](0020-passkeys-and-two-step-login.md) | Passkeys and two-step login in Kodex; a provider is optional | Accepted (2026-10-26) |
| [0021](0021-android-as-built.md) | The Android app: a written client held to the OpenAPI document | Accepted (2026-10-26) |
| [0022](0022-pdf-android-minsdk-28.md) | androidx.pdf only, and minSdk 28 | Accepted (2026-10-26) |
| [0023](0023-trackers-on-the-server.md) | Trackers sync from the server | Accepted (2026-10-26) |
