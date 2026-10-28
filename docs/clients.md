# Reading apps and devices

Kodex has its own Android app, and serves other apps through three
protocols. Each of those needs a personal key, made under Inställningar →
Appar och enheter and shown once.

## The Kodex Android app

Android 9 or later. Each [release](https://github.com/Demacish/kodex/releases)
has the app as `kodex-<version>.apk`, with its SHA-256. It is signed with the
project's key, so a newer one installs over an older one; the certificate's
SHA-256 is
`8b61c574ec87a4b9f37c48a2591e2936e2c313337ff12372e3347a953f40000e`
(`apksigner verify --print-certs` shows it). Builds of the main branch are
the Android workflow's `kodex-android` artifact in GitHub Actions, where
`app.kodex.dev` is the debug build, which installs beside the release.

1. Type the server's address.
2. Log in with your username and password, and with the code from your
   authenticator app if two-step login is on. To use a passkey or the
   identity provider instead, tap the button below the password: the server
   opens in the browser, you approve the app there, and the browser hands
   you back to the app.

The app gets a key of its own, named after the device. It shows under
Inställningar → Appar och enheter, where it can be revoked. The catalog is
kept on the device and syncs in the background. Downloaded books
(Nedladdat) read without a connection, and reading positions are sent when
the device is online again. Under the app's Inställningar you can set:

- downloads on Wi-Fi only;
- how many of the next books in a series download on their own;
- how comics read: direction, two pages side by side, wide pages in halves,
  tap zones, colours.

An EPUB position from the app opens elsewhere at its percentage, and the
app opens other readers' EPUB positions the same way. Comic and PDF pages
are exact everywhere.

## Trackers (MangaUpdates, Kitsu, AniList, MyAnimeList)

What you read in Kodex, in any client, goes to your lists at these services.

1. Under Inställningar → Trackers, connect an account:
   - MangaUpdates: your username and password.
   - Kitsu: your email address and password.
   - AniList and MyAnimeList: log in on their own page. The server needs a
     registered client for these first (`ANILIST_*` and `MYANIMELIST_*` in
     `.env`, see `.env.example`).

   The password isn't kept. The service's token is, encrypted with
   `SECRET_KEY`.
2. On a series' page, choose **Spåra**. When the matcher found the series
   at the service, its entry is offered. Otherwise, search for it there.
   Choose whether a book counts as a volume or a chapter. Kitsu counts
   chapters only.

Every quarter of an hour, each linked series sends the highest number you
have finished. **Skicka nu** sends it at once. Progress only goes forward: a
book marked unread in Kodex, or reading done elsewhere, never lowers what the
service has.

## KOReader (progress sync)

1. Make a **KOReader-synk** key.
2. In KOReader: Tools → Progress sync → Custom sync server:
   `https://<server>/kosync`. Log in with your Kodex username and the key as
   the password.
3. Under Progress sync, set Document matching method to **Binary**.

The newest position wins, as on KOReader's own server. Pages translate
between KOReader and Kodex; an EPUB position from KOReader opens in the web
reader at its progression, and KOReader keeps its own exact position.

## OPDS apps (KOReader, Panels, Chunky, Moon+ Reader, Librera, Cantook, ...)

1. Make an **OPDS-läsare** key.
2. Add a catalog: `https://<server>/opds/` (OPDS 1.2, with page streaming)
   or `https://<server>/opds/v2/catalog` (OPDS 2.0). Any username, the key as
   the password.

Comics stream page by page (OPDS-PSE) in apps that support it, and the page
you are on becomes your position in Kodex. OPDS 2.0 apps that use the
Progression draft sync the position both ways.

## Kobo e-readers

1. Make a **Kobo** key. Its device gets the EPUBs of your "Kobo" collection
   (choose another collection under the key); add books to it in the web
   client.
2. Connect the Kobo by USB and open `.kobo/Kobo/Kobo eReader.conf`. Under
   `[OneStoreServices]`, set the line Kodex showed with the key:
   `api_endpoint=https://<server>/kobo/<key>`.
3. Eject, and sync on the device.

Books arrive as KEPUB; reading positions go both ways. Purchases from the
Kobo store keep syncing (set `KOBO_STORE_PROXY=false` to keep the device off
Kobo's servers). The server needs HTTPS, and a reverse proxy needs room for
long headers (nginx: `large_client_header_buffers 4 32k;`; Caddy is fine as
it is). To undo, put the original `api_endpoint` line back
(`https://storeapi.kobo.com`).

## Verified clients

| Client | Protocol | Browse | Download | Pages | Progress | Checked |
| --- | --- | --- | --- | --- | --- | --- |
| Kodex for Android | Kodex API | | | | | in CI on an emulator; not yet on a device |
| KOReader | KOSync | – | – | – | | not yet |
| KOReader | OPDS 1.2 + PSE | | | | | not yet |
| Panels (iOS) | OPDS 1.2 + PSE | | | | | not yet |
| Moon+ Reader / Librera | OPDS 1.2 | | | – | – | not yet |
| Cantook | OPDS 2.0 + Progression | | | – | | not yet |
| Kobo (KEPUB) | Kobo sync | – | | – | | not yet |
