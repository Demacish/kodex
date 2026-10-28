# 0004. PostgreSQL as the only data store

Status: Accepted

## Context

SQLite would make installation simpler but doubles the test matrix and lacks
what the plan relies on (trigram search, LISTEN/NOTIFY job queue, `uuidv7()`).

## Decision

PostgreSQL 18 holds data, search and the job queue. Tests run against
PostgreSQL only.

## Consequences

The operational cost is real for self-hosters; it is handled with one compose
file, `pg_dump` in the api container, a pinned major version and documented
upgrades. SQLite support is reconsidered after launch.
