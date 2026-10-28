# The API

Everything the web client does goes through the same HTTP API, under
`/api`. It is described by OpenAPI 3.1:

- `/api/openapi.json`: the document; `web/openapi.json` in the repository
  is the same, and CI fails when the two differ (ADR 0013);
- `/api/docs`: the document as browsable pages, on your own server.

## Authentication

- **A personal API key**, made under Inställningar › Appar och enheter:
  `Authorization: Bearer kdx_…`. Use one key per program, so each can be
  revoked on its own. A key acts as its owner, with the owner's role.
- **The web client's session**: a cookie, and for every request that
  changes something, the `X-CSRF-Token` header with the token
  `GET /api/auth/me` returns. Programs shouldn't use sessions.
- **An app on someone's device** gets a key of its own without anyone
  copying one (`/api/auth/app/*`, see `kodex.core.auth.apps`). It logs in
  with a password and a second step, or through the browser with a
  PKCE-style code.

Errors are JSON, `{"detail": "…"}`, with the usual status codes: 401 not
logged in, 403 not allowed, 404 not found, 409 a conflict (a file that
exists, a library that is read-only), 422 a request that doesn't fit the
schema, 429 too many failed logins (with `Retry-After`).

## Keeping a copy in sync

An app that keeps its own copy of the catalog asks for what changed since
it last asked:

    GET /api/sync/changes?since=<cursor>&progress_since=<cursor>&limit=500

The answer has the changed libraries, series, books and the user's
collections, the ids of those that are gone (`deleted`), and the reading
positions changed since `progress_since`. Keep its `cursor` and
`progress_cursor`, and ask again while `more` or `progress_more` is true.
Start with 0 for everything. `reset: true` means the server's history
doesn't go back to your cursor (it was restored from a backup, say): start
again from 0.

`GET /api/books/{id}/file` serves a book's file with `Range` support, so a
stopped download resumes. `GET /api/books/{id}/digest` has the file's
SHA-256 to check it against.

## Reading positions

`PUT /api/books/{id}/progress` reports a position, with `locator_kind`:
`page` for a 0-based page index, `pdf` for a 1-based page number, `cfi`,
`xpointer` (KOReader), `kobo`, `other` (a reader's own form, kept as sent),
or `percent`. Each report goes into the reading journal. With `device_id`,
`client_seq` and `client_at`, a device's late or repeated reports don't
overwrite a newer position.

## Other protocols

These have their own specifications and aren't in the OpenAPI document's
`/api`:

| Path | Protocol |
| --- | --- |
| `/opds/`, `/opds/v2/catalog` | OPDS 1.2 (with page streaming) and OPDS 2.0 |
| `/kosync` | KOReader's progress sync |
| `/kobo/<key>` | Kobo sync |
| `/federation` | Other Kodex servers (with the upload key) |

## Stability

Since 2.0.0 the API follows the version number: a change that breaks a
client waits for a new major version. Every change shows in
`web/openapi.json`'s history and in `CHANGELOG.md`.
