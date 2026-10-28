# Testing

## Principles

- Every backend test runs against PostgreSQL (`tools/test-backend.sh`), never
  SQLite, and builds its schema through the Alembic migrations.
- Tests make no network calls. Metadata providers are exercised with
  responses stored next to the tests and replayed with `respx`.
- Fixtures are either generated (`tools/fixtures/`), public domain
  (Project Gutenberg, fetched into a cache and never committed) or small
  files we made ourselves (`backend/tests/fixtures/`). Real comic or manga
  pages are never committed.

## Provider responses

Matching needs realistic provider responses in tests. They come in two
kinds, and only one of them is ever committed:

| Kind | Where it comes from | Where it lives |
| --- | --- | --- |
| Synthetic | Written by hand from the provider's public API documentation and the shape of real responses, with invented titles and ids | `backend/tests/providers/` (committed) |
| Recorded | Real responses, recorded with the maintainer's own credentials at a low rate | A private directory outside the repository (`KODEX_PRIVATE_DATA`), never committed |

Recorded responses feed the local evaluation against a real library and
let synthetic fixtures be checked against reality; the test suite in CI
uses synthetic responses only. Recording needs the maintainer's keys and
is never done by an agent on its own (see `AGENTS.md`).

### Why nothing recorded is committed

Checked on 2026-10-25:

| Provider | Terms found | Consequence |
| --- | --- | --- |
| Comic Vine | Non-commercial only, link back on pages that use the data, cache responses, 200 requests per resource and hour, "Do not edit, manipulate or reproduce on any other medium", don't build a competing product | Responses may be cached by a running instance, but not reproduced in a repository |
| MangaDex | Free for non-commercial projects that credit MangaDex and scanlation groups; no ads or paid services | Credit MangaDex in the UI; nothing to redistribute |
| Open Library | No new rights asserted, but "existing rights issues on some contributions" | Not clearly redistributable |
| Metron, AniList | Terms pages refuse automated access | Not verified, so not redistributed |
| MangaUpdates, Google Books, Hardcover | Not checked yet | Not redistributed |

The attribution each provider asks for (a link back to Comic Vine, credit
to MangaDex and scanlation groups) is shown in the UI wherever its data
is displayed.

## Test data sets

| Name | Command | Size |
| --- | --- | --- |
| Small synthetic library | `generate_library.py --files 120` (used by `tests/test_fixture_generator.py`) | ~5 MB |
| Gate library | `generate_library.py --files 2000` | ~80 MB, ~6 s |
| Scanner benchmark | `generate_library.py --files 50000` | ~2 GB |
| Gutenberg EPUBs | `fetch_gutenberg.py` | 6 books, ~2 MB |
