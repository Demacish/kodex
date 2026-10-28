# 0005. PostgreSQL full-text and trigram search

Status: Accepted (implemented in phase 4, 2026-10-26)

## Context

v1 runs Meilisearch, a separate service with its own index to keep in sync.

## Decision

`pg_trgm` GIN indexes (`%`, `<%`, `word_similarity`) on titles, aliases and
CJK text, and `tsvector` with `websearch_to_tsquery` on summaries and full
text, ranked together. (The plan kept Meilisearch as an option behind a
`SearchBackend` interface; see below.)

As built (`kodex.discovery.search`, migration 0013): a book is found when
every word of the query is in its title, series, authors, genres, tags,
story arcs or publisher (as substrings, which also finds CJK titles), when
the query is close to the title or series by word similarity (typos), or
when its summary matches the query as full text. Hits rank by how close
the title or series is. Book text from the full-text job is searched with
`websearch_to_tsquery`, and its snippet is escaped before the hit is
marked. Both use the `simple` configuration, so no language gets stemming.
Smart collections' rules are SQL too (`kodex.collections.rules`), so
nothing needs an index outside the database.

Meilisearch is removed rather than kept behind an interface: nothing needed
it once search and smart collections were SQL, and one service less is the
point. It can come back behind an interface if a library outgrows this.

## Consequences

One service less to run (and its memory). No CJK tokenisation in full text;
titles in CJK are found by substring and trigrams. A word in a summary or a
book's text matches only as written ("storm" doesn't find "stormen").
