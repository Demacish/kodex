# Acquisition (an add-on, off by default)

With the add-on on, a missing issue goes from a request to a book in its
series: someone requests it, an admin approves it, and Kodex does the rest.

## What happens

1. On a series' page, the missing numbers show under the reading progress.
   Choose **Önska dem**, then the numbers. Each becomes a request
   ("Stjärnhavet #2") that the admins see under Önskemål.
2. An admin approves the request.
3. Kodex searches Prowlarr for the series' title and the number. It takes the
   best result that has the series' title and that number, and not a run of
   numbers ("001-012"). A year in the title doesn't count as a number.
   Torrents go to qBittorrent, which takes magnet links only. NZBs go to
   SABnzbd.
4. Every two minutes Kodex asks the clients how the downloads are doing.
   When one is done, its comic and book files (`.cbz`, `.cbr`, `.cb7`,
   `.epub`, `.pdf`) are moved into the series' folder. Anything else in the
   download stays where it was.
5. The library is scanned, which also matches the new book. Once the series
   has the number, the request is fulfilled, and the person who asked gets
   an ntfy message if they set a topic under Inställningar.

When Prowlarr has nothing that fits, the request stays approved and gets a
note saying what was searched for. The admin can then find the file another
way, or upload it to the library.

## Setting it up

Kodex starts none of these programs; they run wherever you have them. In
`.env`:

    ACQUIRE_ENABLED=true
    PROWLARR_URL=http://prowlarr:9696
    PROWLARR_API_KEY=…
    # torrents:
    QBITTORRENT_URL=http://qbittorrent:8080
    QBITTORRENT_USERNAME=…
    QBITTORRENT_PASSWORD=…
    # and/or Usenet:
    SABNZBD_URL=http://sabnzbd:8080
    SABNZBD_API_KEY=…
    # where qBittorrent saves; the worker must see the same files:
    DOWNLOADS_STAGING_DIR=/data/downloads

If the download client sees the files at another path than Kodex's worker,
map one onto the other: `DOWNLOAD_PATH_MAP_TORRENT=/downloads:/data/downloads`
(and `DOWNLOAD_PATH_MAP_USENET` for SABnzbd).

Mylar3, Kapowarr, Anna's Archive and GetComics are reached by hand, and
for now only through the API: `POST /api/requests/{id}/send-to-mylar3` (or
`send-to-kapowarr`) hands a request's Comic Vine volume over, and
`GET /api/downloads/search-annas-archive` and `…/search-getcomics` with
`POST /api/downloads/from-annas-archive` and `…/from-getcomics` download
one file. The web client has no page for them yet.

## Off

With `ACQUIRE_ENABLED=false` (the default), requests are a wish list for the
admins: approving one changes nothing else.
