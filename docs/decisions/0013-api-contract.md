# 0013. OpenAPI 3.1 as the API contract

Status: Accepted (implemented in phase 3)

## Context

v1 clients use hand-written DTOs that drift from the server.

## Decision

FastAPI's OpenAPI 3.1 document is the contract. TypeScript and Kotlin clients
are generated in CI, and a contract test runs on every pull request. A
breaking change needs a version bump.

## Consequences

Third-party clients get a reliable API.
