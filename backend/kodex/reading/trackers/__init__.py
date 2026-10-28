"""Trackers: a reader's lists at MangaUpdates, Kitsu, AniList and
MyAnimeList, kept up to date from Kodex's reading positions, whichever
client the reading was done in (ADR 0023).

A user connects an account under Inställningar (a password for
MangaUpdates and Kitsu, the service's own login page for AniList and
MyAnimeList, which need a registered client); a series is linked to the
service's entry, suggested from the series' external ids when the matcher
found one. Every quarter of an hour the books read in each linked series
go to the service as volumes or chapters read: only forward, never below
what the service already has."""
