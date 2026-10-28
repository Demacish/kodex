"""Application settings, loaded from environment variables (or a .env file in dev).

See ../../.env.example at the repo root for the full list of variables a
deployment needs to set.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore", validate_by_name=True)

    # --- Database ---
    database_url: str = "postgresql+psycopg://kodex:kodex@localhost:5432/kodex"

    # --- Background jobs ---

    # --- Library storage ---
    # Root directory under which every Library.path must live. Keeps the API
    # from being pointed at arbitrary filesystem paths.
    libraries_root: Path = Path("/libraries")

    # Where extracted cover images are cached.
    covers_dir: Path = Path("/data/covers")

    # --- Archive decoding ---
    # CBR entries are decompressed with unar, falling back to bsdtar
    # (libarchive); both are open source. unrar is not used.
    unar_binary: str = "unar"
    bsdtar_binary: str = "bsdtar"
    # Processes a scan reads new and changed files with; 0 means one per
    # CPU. The database work stays in the scanning process.
    scan_workers: int = 0
    # Libraries are rescanned when this long has passed since their last
    # scan (polling, for network shares without file events); 0 turns it off.
    rescan_interval_minutes: int = 60
    # Ended jobs and their results are kept this long for the job overview.
    job_retention_days: int = 14
    # The reading journal keeps every position this long; older days keep
    # their last position per book, and every finish and restart.
    reading_journal_days: int = 90
    # Kobo sync (kodex.reading.kobo): kepubify turns EPUBs into KEPUBs for
    # Kobo's own reader (without it the device gets the EPUB). Requests the
    # sync doesn't answer itself go on to Kobo's store, so the device keeps
    # its store purchases and settings; false answers them with nothing.
    kepubify_binary: str = "kepubify"
    kobo_store_proxy: bool = True

    # --- Auth: an OpenID Connect provider, optional (kodex.core.auth) ---
    # When true, authentication is bypassed entirely and every request is
    # treated as a fixed development user. NEVER enable this in production.
    auth_disabled: bool = False
    # Any provider with discovery (Authentik, Keycloak, Authelia, Zitadel,
    # Pocket ID, ...): people log in with it beside or instead of a Kodex
    # password, and apps may send its access tokens as bearer tokens. Empty
    # issuer: Kodex accounts only. v1's AUTHENTIK_* names still work.
    oidc_issuer: str = Field("", validation_alias=AliasChoices("oidc_issuer", "authentik_issuer"))
    oidc_client_id: str = Field("", validation_alias=AliasChoices("oidc_client_id", "authentik_client_id"))
    # Empty for a public client (PKCE only). The provider must allow
    # <this server>/api/auth/oidc/callback as a redirect URI.
    oidc_client_secret: str = Field("", validation_alias=AliasChoices("oidc_client_secret", "authentik_client_secret"))
    oidc_scopes: str = "openid profile email groups"
    # The name on the login button; empty shows a generic one.
    oidc_display_name: str = ""
    oidc_groups_claim: str = Field(
        "groups", validation_alias=AliasChoices("oidc_groups_claim", "authentik_groups_claim")
    )
    # Only members of this group may log in (empty: everyone the provider
    # lets through); with an admin group, membership decides who is an admin.
    oidc_required_group: str = Field(
        "", validation_alias=AliasChoices("oidc_required_group", "authentik_required_group")
    )
    oidc_admin_group: str = Field("", validation_alias=AliasChoices("oidc_admin_group", "authentik_admin_group"))
    # Whether a first login through the provider creates an account; false
    # lets in only accounts that were linked under Inställningar.
    oidc_create_users: bool = True
    # A second client at the same provider whose tokens apps send (v1's
    # Android app has its own public client, since Authentik can't combine
    # confidential and public clients in one provider). Leave both empty
    # if there is none.
    oidc_mobile_client_id: str = Field(
        "", validation_alias=AliasChoices("oidc_mobile_client_id", "authentik_mobile_client_id")
    )
    oidc_mobile_issuer: str = Field("", validation_alias=AliasChoices("oidc_mobile_issuer", "authentik_mobile_issuer"))

    # --- Trackers (kodex.reading.trackers) ---
    # Encrypts the tokens of the users' tracker accounts; any long random
    # string (`openssl rand -base64 32`). Changing it disconnects them.
    secret_key: str = ""
    # AniList and MyAnimeList need a client registered with them (free):
    # AniList under Settings → Developer, MyAnimeList at
    # myanimelist.net/apiconfig. The redirect URI to register is
    # <this server>/api/trackers/anilist/callback (or …/myanimelist/callback).
    # Empty leaves the service out. MangaUpdates and Kitsu need nothing.
    anilist_client_id: str = ""
    anilist_client_secret: str = ""
    myanimelist_client_id: str = ""
    myanimelist_client_secret: str = ""
    # Kitsu's password login works without a client; its API documentation
    # names one that may be set here if Kitsu starts to require it.
    kitsu_client_id: str = ""
    kitsu_client_secret: str = ""

    # --- Local accounts and sessions (kodex.core.auth) ---
    local_login_enabled: bool = True
    session_days: int = 30
    # "auto" marks cookies Secure when the request came over HTTPS (behind a
    # proxy that sets X-Forwarded-Proto; uvicorn trusts it from the addresses
    # in FORWARDED_ALLOW_IPS); "true" or "false" forces it.
    cookie_secure: str = "auto"
    # Failed password logins: one username, or one address, waits once it
    # has this many within login_lockout_minutes.
    login_max_failures: int = 5
    login_max_failures_per_ip: int = 30
    login_lockout_minutes: int = 15
    # Passkeys (WebAuthn) for logging in without a password, and as a second
    # step after one; off when local logins are. They belong to one host
    # name: PUBLIC_APP_URL's when it is set, otherwise the one the browser used.
    passkeys_enabled: bool = True

    # --- Send-to-device ---
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from_address: str = ""

    # --- Metadata enrichment ---
    # Comic Vine requires a free API key (https://comicvine.gamespot.com/api/).
    # AniList and Open Library need no key. If comicvine_api_key
    # is empty, Comic Vine enrichment is skipped and logged once rather than
    # failing every comic book.
    comicvine_api_key: str = ""
    # Google Books (EBOOKS fallback when Open Library has nothing useful) -
    # optional but strongly recommended: anonymous requests hit Google's
    # shared rate limit almost immediately (confirmed 2026-09-17 - every
    # single anonymous call during a full-library enrichment run got 429,
    # 0 successful Google Books matches). A free key from
    # https://console.cloud.google.com/ (enable "Books API") gets a much
    # higher quota. Empty by default: falls back to the old anonymous
    # behaviour.
    google_books_api_key: str = ""
    # Metron (https://metron.cloud/) — optional, layered on top of a Comic
    # Vine match purely for better story-arc discovery (see
    # app/enrichment/metron.py's own docstring for why). HTTP Basic Auth
    # against a real Metron account (its own username/password — 2026-09-11,
    # explicitly requested over the token-based alternative Metron also
    # supports). Empty by default: story arc discovery then falls back to
    # Comic Vine's own (sparser) story_arc_credits, same as before this
    # was added.
    metron_username: str = ""
    metron_password: str = ""
    # FlareSolverr instance (a separate container) used only by
    # app/enrichment/leagueofcomicgeeks.py — League of Comic Geeks sits
    # behind a Cloudflare JS challenge that a plain httpx request can't
    # pass (403 "cf-mitigated: challenge"), same class of block that
    # already ruled out Metron before this workaround existed. Empty by
    # default: the LoCG import endpoint then reports itself unconfigured
    # rather than failing every request against an unreachable URL.
    flaresolverr_url: str = ""
    enrichment_http_timeout_seconds: float = 15.0
    # Sent as the User-Agent on every enrichment request — Open Library and
    # AniList both ask API consumers to identify themselves.
    enrichment_user_agent: str = "kodex (https://github.com/Demacish/kodex) contact: set ENRICHMENT_USER_AGENT"
    # Hardcover's GraphQL API (e-book editions by ISBN). Optional.
    hardcover_api_token: str = ""
    # Match new series (kodex.matching) right after a scan finds books in
    # series that were never matched.
    match_after_scan: bool = True
    # Only these metadata sources, comma-separated (comicvine, metron,
    # mangadex, anilist, mangaupdates, open_library, google_books,
    # hardcover); empty uses every one that is set up, and "none" turns the
    # lookups off (series stay unmatched).
    matching_providers: str = ""

    # --- Requestsystem: notifications ---
    # Both optional and independent of each other — set either, both, or
    # neither. See kodex/delivery/notify.py. Leaving both empty just
    # means new requests only show up in the admin queue, no push.
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    discord_webhook_url: str = ""

    # --- Guided View (panel-by-panel reading for CBZ/CBR/image-folder books) ---
    # Experimental — see app/panels/detector.py. A single flag kills the
    # whole feature without a redeploy if the detection heuristic turns out
    # not to work well enough in practice: false stops new detection jobs
    # from being enqueued AND makes GET /books/{id}/pages/{n}/panels return
    # an empty list regardless of what's already stored in book_page_panels
    # — so turning this off makes Guided View disappear from the reader
    # immediately, with no need to also clear out already-detected data.
    guided_view_enabled: bool = True

    # --- Automatic sorting of the intake library (kodex/acquire/sorting/) ---
    # When the intake library (type "mixed") is scanned, new top-level
    # items are always classified into the sorting queue first (see
    # scan_library_task). With this on, the confidently classified ones
    # (status RESOLVED) are also moved to their comics/manga/ebooks
    # destination library right away, before the intake itself is
    # scanned — the same move "Verkställ sortering" does by hand.
    # Uncertain items always stay in the review queue either way. Set
    # SORTING_AUTO_APPLY=false to only classify and keep moving manual.
    sorting_auto_apply: bool = True

    # --- Shared reading progress with a central Kodex server ---
    # Set on every server EXCEPT the central one (see app/progress/
    # upstream.py): the central server's kosync address, e.g.
    # https://kodex.example.com/api/kosync — whatever reaches its backend's
    # /kosync — plus the username and OPDS token of the account to sync as
    # there. All three empty = no syncing (a standalone or central server).
    progress_sync_url: str = ""
    progress_sync_username: str = ""
    progress_sync_token: str = ""
    # How this server shows up as the "device" on the central one, e.g.
    # "Hemma-NAS". Optional.
    progress_sync_device_name: str = ""

    # --- Push notifications via ntfy (also a UnifiedPush distributor) ---
    # Each user picks their own topic under Inställningar; this is the ntfy
    # server those topics live on — ntfy.sh, or your own self-hosted one.
    # NTFY_TOKEN is only needed if that server requires auth to publish.
    ntfy_url: str = "https://ntfy.sh"
    ntfy_token: str = ""
    # The app's public address (e.g. https://kodex.example.com), for links
    # in notifications and sign-in links, the OpenID Connect redirect URI
    # and the passkeys' host name. Optional: the request's address otherwise.
    public_app_url: str = ""
    # The built web client (web/dist), served by the api; the image has it
    # here. Without it the api serves only the API.
    web_dist_dir: str = "/app/web"

    # --- AI recommendations/collections (app/ai/) ---
    # One shared, admin-configured key for the whole instance (matching
    # comicvine_api_key/telegram_bot_token's existing convention above)
    # rather than a per-user key — see the app's own request-vs-admin
    # split elsewhere, this is a shared-catalog personal server, not a
    # multi-tenant one. Empty ai_provider disables both the "För dig"
    # recommendations feed and admin AI-collection generation entirely
    # (same "empty key = feature quietly skipped" pattern as Comic Vine).
    ai_provider: str = ""  # "openai" | "claude" | "gemini" — see AIProvider
    ai_api_key: str = ""
    # Optional per-provider model override — empty uses app/ai/'s own
    # per-provider default (see each client module's DEFAULT_MODEL).
    ai_model: str = ""

    # --- Public stats endpoint (for a homepage-dashboard widget) ---
    # GET /stats requires this exact value in an X-Kodex-Api-Key header —
    # separate from normal user auth so a dashboard can read it without
    # logging in as a user. Empty disables the endpoint entirely (401 on
    # every request) rather than leaving it open by accident.
    stats_api_key: str = ""

    # --- Acquisition, an add-on that is off by default (kodex.acquire, docs/acquire.md) ---
    # On: an approved request for a missing issue is searched for in
    # Prowlarr, downloaded with qBittorrent or SABnzbd, imported into its
    # series' folder and scanned, with no one doing more than approving.
    acquire_enabled: bool = False

    # --- Nedladdningsautomation (Batch C, kodex/acquire/clients/) ---
    # Optional: every URL points at a download client running elsewhere —
    # nothing here is started by docker-compose. Empty disables that part.
    qbittorrent_url: str = ""
    qbittorrent_username: str = ""
    qbittorrent_password: str = ""
    sabnzbd_url: str = ""
    sabnzbd_api_key: str = ""
    prowlarr_url: str = ""
    prowlarr_api_key: str = ""
    flaresolverr_url: str = ""
    # Delad hemlighet i webhook-anropet nedladdningsklienten gör vid
    # färdig nedladdning (POST /downloads/{id}/webhook-complete?token=...)
    # — inte en OIDC-session, klienten är inte en inloggad användare.
    download_webhook_secret: str = ""
    # "host_prefix:container_prefix" — översätter nedladdningsklientens
    # egen sökväg (på VAD DEN ser som "host") till sökvägen Kodex worker-
    # containern ser, om de två containrarna monterar samma volym på
    # olika ställen. Tomt = ingen översättning (samma sökväg för båda).
    download_path_map_torrent: str = ""
    download_path_map_usenet: str = ""
    # Var på Kodex-sidan färdiga nedladdningar hamnar innan de flyttas in
    # i rätt bibliotek av import_completed_download_task.
    downloads_staging_dir: Path = Path("/data/downloads")
    # Anna's Archive (C13) — interaktiv källa, ingen API-nyckel krävs
    # (spärrade filer hamnar i manuell granskning i stället för att
    # hämtas automatiskt). Speglar roterar ofta — kommaseparerad lista
    # (samma enkla platta strängkonvention som resten av .env.example,
    # inte pydantic-settings' JSON-parsning av list-fält), provade i
    # ordning tills en svarar. Se kodex/acquire/clients/annas_archive.py.
    annas_archive_mirrors: str = ""
    # Mylar3/Kapowarr (requested 2026-09-21) — full comic managers running
    # on a separate, user-managed host, reached via their own REST APIs.
    # Kodex only ever tells them "start tracking/searching for this
    # Comic Vine volume id" (see kodex/acquire/clients/mylar3.py/kapowarr.py) —
    # it has no visibility into their own download pipeline or when a
    # file actually lands, unlike the qBittorrent/SABnzbd path above.
    # The finished file gets INTO Kodex via a script running on that
    # same external host, watching its own completed-downloads folder
    # and POSTing to the existing POST /libraries/{id}/upload (B7) —
    # see upload_api_key below for how that script authenticates.
    mylar3_url: str = ""
    mylar3_api_key: str = ""
    kapowarr_url: str = ""
    kapowarr_api_key: str = ""
    # Kapowarr requires a root_folder_id (one of ITS OWN configured
    # library roots) on every add-volume call — no sane per-request
    # default exists, so this has to be admin-configured once (see
    # Kapowarr's own GET /api/rootfolder to find the id). A plain string
    # (not int | None) like every other optional setting in this file —
    # pydantic-settings can't coerce an empty env var string to None for
    # a typed-int field, it just fails Settings() construction outright
    # (found breaking every deploy 2026-09-22 right after this was
    # added). kodex/acquire/clients/kapowarr.py parses it at call time instead.
    kapowarr_root_folder_id: str = ""
    # A shared secret for the B7 upload endpoint's headless/script auth
    # path — the external device's folder-watcher script is not a
    # logged-in Kodex user and can't do an interactive Authentik login,
    # so it authenticates with this instead (sent as X-Kodex-Upload-Key),
    # same "simple shared secret for machine-to-machine" pattern as
    # download_webhook_secret/stats_api_key above. Empty disables this
    # auth path entirely — the endpoint still works normally for a real
    # admin's browser session either way.
    upload_api_key: str = ""

    # --- Other Kodex servers ("Kopiera vol 5–10 till Hemma-NAS") ---
    # A JSON list of the other servers this one can see and copy books to,
    # e.g. [{"name": "Hemma-NAS", "url": "http://nas.example.lan:20100",
    # "upload_key": "<that server's UPLOAD_API_KEY>"}]. `url` is the other
    # server's BACKEND (the API, not the web app). A plain string parsed by
    # kodex/delivery/federation/peers.py rather than a typed list, so a typo here logs an error
    # and disables the feature instead of failing Settings() — and every
    # deploy — outright (see kapowarr_root_folder_id above).
    kodex_peers: str = ""


@lru_cache
def get_settings() -> Settings:
    # NAME_FILE secrets also for commands run without the entrypoint
    # (`docker compose exec api python -m …`).
    from kodex.core.entrypoint import load_file_secrets

    load_file_secrets()
    return Settings()
