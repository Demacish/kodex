# 0011. Kotlin and Compose with a shared KMP module

Status: Accepted; superseded by [0021](0021-android-as-built.md) where they differ (2026-10-26)

## Context

The v1 Android app was never built in CI and is restarted. Considered:
Kotlin/Compose, Flutter, React Native, KMP.

## Decision

Kotlin + Compose with `shared/` as a Kotlin Multiplatform module (Ktor client,
models, sync, journal queue, Room KMP), Koin for DI, Navigation 3, Coil 3,
Paging 3, WorkManager. Readium Kotlin 3.4 with `EpubNavigatorFragment` and
`TtsNavigator` (the Compose navigators are alpha). No iOS targets in CI until
needed.

## Consequences

Desktop or iOS later reuse the API layer and sync, as Komelia shows.
