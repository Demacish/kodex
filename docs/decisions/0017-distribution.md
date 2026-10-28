# 0017. Docker Compose as the distribution

Status: Accepted

## Context

Self-hosters run Docker on NAS boxes and small servers. Alternatives: a single
binary, OS packages.

## Decision

Two containers (`api+worker` from one image, and `postgres`), images for
x86-64 and arm64; search is PostgreSQL's (ADR 0005). Details in ADR 0018.

## Consequences

Installation instructions are a compose file and an `.env`.
