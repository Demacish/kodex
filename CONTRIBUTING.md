# Contributing

Kodex is being rebuilt in phases (see [`docs/plan.sv.md`](docs/plan.sv.md) and
[`AGENTS.md`](AGENTS.md)). This page covers the practical side.

## Requirements

- Docker with Compose v2 (backend tests and the full stack run in containers)
- Node.js 24 and npm (the web client in `web/`)
- Optional: Python 3.14 for running backend tools outside Docker

## Backend

Tests run against PostgreSQL 18 and need `unar` and `bsdtar`; the script
below provides both in Docker:

```bash
tools/test-backend.sh -q                      # whole suite
tools/test-backend.sh tests/test_scanner.py   # one file, any pytest args
KODEX_TEST_CMD="ruff check . ../tools && ruff format --check . ../tools && mypy" tools/test-backend.sh
```

Without Docker, point `TEST_DATABASE_URL` at an empty Postgres database
(it is wiped by the test run) and run `pytest` from `backend/` after
`pip install -r requirements-dev.txt`.

### Database migrations

The schema belongs to Alembic (`backend/kodex/core/migrations/`). After
changing a model:

```bash
cd backend
DATABASE_URL=postgresql+psycopg://… alembic revision --autogenerate -m "short description"
```

Review the generated file, then run the suite: `tests/test_migrations.py`
fails if head doesn't match the models. The API container applies
migrations on start with `python -m kodex.core.migrate`, which also adopts
v1 databases.

### Style

`ruff format` and `ruff check` (config in `backend/pyproject.toml`), `mypy`
strict for `backend/kodex/`. Install the hooks with:

```bash
pip install pre-commit
pre-commit install --hook-type pre-commit --hook-type commit-msg
```

## Web app

```bash
cd web
npm ci
npm run typecheck && npm test && npm run build
```

`npm run dev` serves it with an API on `KODEX_API` (`tools/dev-stack.sh`
starts one on a synthetic library). `npm run e2e` runs the browser tests
against `KODEX_WEB_URL`; `tools/smoke-compose.sh` starts the whole stack
for them. These need a few GB of memory; on a smaller machine let CI run
them (`gh workflow run ci.yml --ref <branch>`).

## Android app

The app (`androidApp/`) and its plain-Kotlin core (`shared/`) build with the
Gradle wrapper at the repository's root. You need JDK 21 and the Android SDK
(compileSdk 37).

```bash
./gradlew :shared:jvmTest                          # the core, with the API contract test
./gradlew :androidApp:testDebugUnitTest :androidApp:lintDebug
./gradlew :androidApp:assembleDebug                # androidApp/build/outputs/apk/debug/
./gradlew :androidApp:connectedDebugAndroidTest    # on a device or an emulator
```

`shared/`'s contract test holds the app's API client to `web/openapi.json`:
a server change the app can't handle fails the app's build. A Gradle build
wants several GB of memory. On a smaller machine, let the Android workflow
build it (`gh workflow run android.yml --ref <branch>`).

## Test fixtures

- `tools/fixtures/generate_library.py --out DIR --files N` writes a
  synthetic library with drawn pages and a ground-truth `manifest.json`.
- `tools/fixtures/fetch_gutenberg.py --out DIR` fetches the public-domain
  EPUBs listed in `tools/fixtures/gutenberg.json` (never committed).
- `backend/tests/fixtures/` holds small committed files (prebuilt RAR
  archives). See [`docs/testing.md`](docs/testing.md) for the policy on
  recorded provider responses.

## Commits and pull requests

- Conventional Commits: `type(scope): description`, types `feat`, `fix`,
  `perf`, `refactor`, `test`, `docs`, `build`, `ci`, `chore`, `style`,
  `revert`. CI checks pull requests with `tools/check-commits.sh`.
- Add user-visible changes to `CHANGELOG.md` under *Unreleased*.
- No secrets, host names or personal data anywhere in the repository.
