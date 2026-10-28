# Working on Kodex as an agent

Read this before changing anything. It applies to AI coding agents and
humans alike.

## The work order

[`docs/plan.sv.md`](docs/plan.sv.md) is the binding plan (in Swedish). Read
it in full before coding. Work phase by phase, one task at a time, and do
not start a phase before the previous phase's gate is met. Its glossary is
binding: *Serie*, *Run*, *Volymnummer*, *Volym*, *Nummer*, *Kapitel* and the
rest mean exactly what it says, in code, API and UI. Never call a Comic Vine
volume a "volume" in code; it is a `run`. Series metadata matching has
priority over new reader features.

Architecture decisions live in [`docs/decisions/`](docs/decisions/). A change
that contradicts one needs a new ADR first.

## Stop and ask

Stop and ask the maintainer instead of guessing when a task needs:

- a secret, API key or account (including recording provider responses),
- access to an external service or account beyond public documentation,
- a destructive or irreversible change: dropping or rewriting data, a
  migration that can lose rows, deleting files in a library, force-pushing,
- a decision the repository and the plan don't settle.

## Layout

| Path | What |
| --- | --- |
| `backend/kodex/` | v2 modules (`core`, `library`, `formats`, `matching`, `reading`, `collections`, `discovery`, `acquire`, `delivery`, `jobs`) |
| `backend/app/` | v1 code, moved into `kodex/` one module at a time |
| `backend/kodex/core/migrations/` | Alembic; the only way the schema changes |
| `backend/tests/` | pytest, always against PostgreSQL |
| `web/` | the web client: Vite, React, TanStack, Tailwind; `e2e/` holds the browser tests |
| `tools/` | test runners, fixture generators, maintenance scripts |
| `docs/` | plan, ADRs, guides |

## Commands

```bash
tools/test-backend.sh                    # pytest against a throwaway Postgres 18, in Docker
tools/test-backend.sh tests/test_api.py -x
KODEX_TEST_CMD="ruff check . ../tools && ruff format --check . ../tools && mypy" tools/test-backend.sh
(cd web && npm ci && npm run typecheck && npm test && npm run build)
tools/smoke-compose.sh                   # whole stack in Docker + Playwright
gh workflow run ci.yml --ref <branch>    # all of the above in GitHub Actions
```

The scripts start containers and build images. On a small or shared machine
(a home server running other services) don't run them there: push the branch
and let CI run them, or start CI by hand with `gh workflow run`, then follow
it with `gh run watch`. The same goes for `tools/dev-stack.sh` and long-lived
dev servers.

## Rules

- **Tests stay green.** Backend `pytest`, lint (`ruff`), types (`mypy`, strict
  for `kodex/`), web `typecheck`, `test` and `build`, and the compose smoke
  test. A task is done when CI says so, not when the code is written.
- **PostgreSQL only.** No SQLite, not even in tests.
- **Schema changes are Alembic migrations** (`alembic revision --autogenerate`,
  then review). Never `create_all()` or hand-run `ALTER TABLE`. A migration
  must work on a database adopted from v1; `tests/test_migrations.py` checks
  that head matches the models.
- **No network in tests.** Provider calls use recorded responses.
- **Docker is the deployment target.** Everything the server needs is in the
  image; configuration comes from environment variables; state lives only in
  volumes. See the plan's "Docker‑kompatibel server".
- **Nothing instance-specific in the repository**: no domains, host names,
  keys or personal data in code, tests, fixtures or docs. Use placeholders
  like `example.com` and environment variables.
- **License: MIT.** Don't add dependencies whose license isn't compatible
  (no AGPL or GPL libraries in the server). Record provenance of anything
  copied in `NOTICE`.
- **Commits** follow [Conventional Commits](https://www.conventionalcommits.org)
  (`feat(matching): …`); user-visible changes go in `CHANGELOG.md`.
- Code identifiers, comments and public docs are in English; the UI is
  translated (sv/en from phase 3).
