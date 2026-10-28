# Why PostgreSQL (and not SQLite)

Many self-hosted readers use SQLite: it needs no server of its own, and a
library is one file. Kodex uses PostgreSQL, and nothing else: no Redis, no
search engine, no message queue. One more container is a real cost for a
self-hoster, so here is what it buys (ADR 0004 and 0005).

- **Search** is PostgreSQL's own. It covers:
  - full-text search (`tsvector`);
  - fuzzy matching on titles (`pg_trgm` word similarity, so a typo still
    finds the series);
  - substring search for Japanese, Chinese and Korean titles, which have
    no spaces to split words at.

  v1 ran Meilisearch beside it, with its own memory and its own index to
  keep in step.
- **Jobs** (scans, matching, covers, downloads, backups) are a queue in
  the same database (Procrastinate), so a backup holds them too and there
  is no second system to keep running. Periodic jobs run once however
  many workers there are. v1 needed Redis for this.
- **Smart collections** ("unread issues of series I follow", "the next
  unread in each story arc") are rules turned into SQL, evaluated by the
  database over the whole library, per reader.
- **Delta sync for apps** is a log that triggers write as rows change,
  with a cursor per client, in the same transaction as the change.
- **Many readers at once.** A scan writes while people read, the worker
  writes while the api serves, and a Kobo syncs while KOReader reports a
  position. PostgreSQL's row locking takes that; SQLite has one writer at
  a time.
- **One tested target.** Kodex runs its tests against PostgreSQL only.
  Supporting both would double the test matrix and hold every feature to
  what SQLite can do.

What it costs, and how Kodex keeps that small:

- One compose file starts it, with the major version pinned.
- Backups are built in: a nightly dump, a restore drill, and documented
  restores ([operations.md](operations.md#backups)).
- Major version upgrades are documented
  ([operations.md](operations.md#upgrading-postgresql-to-a-new-major-version)).
- With a few hundred books it uses about 50 MB of memory; with 50 000, at
  most 600 MB, most of it the page cache, which the kernel takes back when
  memory is short ([operations.md](operations.md#memory)).

SQLite support may be reconsidered after the first release, if the cost
turns out to keep people away.
