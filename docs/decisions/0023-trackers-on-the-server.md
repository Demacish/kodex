# 0023. Trackers sync from the server

Status: Accepted (2026-10-26, phase 5)

## Context

The plan put trackers (AniList, MyAnimeList, MangaUpdates, MangaBaka) in the
Android app as an optional sync, the way Mihon has them. But a Kodex reader
also reads in the web client, in KOReader and on a Kobo. All of them report
to the server's reading journal. A tracker in the app would see only the
app's reading.

The services differ in what they need:

- MangaUpdates logs in with a username and password and gives a session
  token.
- Kitsu has an OAuth password grant.
- AniList and MyAnimeList need a client registered with them, and send the
  browser back to a fixed redirect URI. Each server registers its own.
- MangaBaka has user routes but doesn't document them.

## Decision

- Trackers are in the server (`kodex.reading.trackers`), for MangaUpdates,
  Kitsu, AniList and MyAnimeList.
- A user connects an account under Inställningar: with a password for
  MangaUpdates and Kitsu, which isn't kept, or on the service's own page for
  AniList and MyAnimeList. Their client is set with `ANILIST_*` and
  `MYANIMELIST_*`.
- The tokens are encrypted with a key derived from `SECRET_KEY`.
- A series is linked to the service's entry. When the matcher has found the
  series at that service, the link is suggested from its external id.
- Every quarter of an hour, each linked series sends the highest whole
  number among its finished books, as volumes or chapters read, or the
  number of finished books when they have none. Kitsu counts chapters only.
- Progress only goes forward: never below what Kodex sent last, nor below
  what the service already has.
- A series is marked completed when the service knows its length and it has
  been reached.

## Consequences

- Reading on any client reaches the trackers, and the Android app needs no
  tracker code.
- An admin sets `SECRET_KEY`, and registers clients for AniList and
  MyAnimeList, before people can use those two.
- MangaBaka, Shikimori and Bangumi can be added behind the same interface
  when wanted.
- Western comics have no tracker with an open API (League of Comic Geeks has
  none).
