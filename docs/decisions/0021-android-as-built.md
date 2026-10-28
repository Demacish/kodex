# 0021. The Android app as built: a written client held to the OpenAPI document

Status: Accepted (2026-10-26, phase 5). Supersedes [0011](0011-android.md) where they differ.

## Context

ADR 0011 chose Kotlin and Compose with a shared Kotlin Multiplatform module, and
listed what the module would hold, Room KMP and Paging 3 among them. Building
phase 5 showed three places where less is better:

- A client generated from the OpenAPI document (openapi-generator's Kotlin
  multiplatform output) brings its own HTTP and serialization layer and every
  schema the server has (164 of them) for the dozen calls the app makes. Its
  models change name whenever a schema does.
- The catalog lives on the device, so the database is the app's, not
  something a second platform would share as is.
- The app's lists are a library's series and a series' books: hundreds of
  rows, which Room's flows give at once. Paging adds nothing there.

## Decision

- `shared/` is a Kotlin Multiplatform module with only a JVM target, which
  Android consumes. It holds the Ktor client (`KodexApi`), written by hand
  for the calls the app makes, with `@Serializable` models of the fields it
  reads; delta sync (`SyncEngine`, over a `CatalogStore` interface); the
  queue of reading positions (`ProgressSender`, over an `Outbox`); and the
  reader's rules that must match the server and the web (page layout, page
  order in archives, page positions).
- `ContractTest` holds the client to `web/openapi.json`, which the backend's
  CI keeps current. It checks that every endpoint the app calls exists, that
  every field the app reads is sent and is never null where the app can't
  take null, and that every field the server requires is one the app sends.
  A server change that would break the app fails the app's build.
- Room 3 (`androidx.room3`) is in the app: the catalog, the positions read
  on the device and not yet sent, and the downloads.
- No Paging 3.

## Consequences

- A new call is a function and a model in `shared/` and a line in
  `ContractTest`; nothing is generated.
- An iOS or desktop app later adds a target to `shared/` and brings its own
  database behind `CatalogStore` and `Outbox`.
- Unknown fields are skipped and enums are strings, so an older app keeps
  working against a newer server.
