# 0002. Python and FastAPI for the backend

Status: Accepted

## Context

Alternatives: Go, Kotlin/Spring (Komga), Rust (Stump), .NET (Kavita). Matching
is the priority area, and v1 has ~500 Python tests.

## Decision

Python 3.14 with FastAPI. The ecosystem for matching is the strongest
(`rapidfuzz`, `imagehash`/Pillow, `pypdfium2`, `rarfile`, `httpx`). The floor
is 3.11 (Pillow 13, SQLAlchemy 2.1); 3.14 is the current stable release with
years of support left.

## Consequences

CPU-heavy work (hashing, image re-encoding, extraction) runs in process pools,
never in the event loop. The v1 tests come along unchanged.
