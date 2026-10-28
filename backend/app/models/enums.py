import enum


class LibraryType(str, enum.Enum):
    COMICS = "comics"
    EBOOKS = "ebooks"
    MANGA = "manga"
    MIXED = "mixed"


class BookFormat(str, enum.Enum):
    EPUB = "epub"
    PDF = "pdf"
    CBZ = "cbz"
    CBR = "cbr"
    CB7 = "cb7"
    IMAGE_FOLDER = "image_folder"


# Single-file comic archives, and every format that is read page by page.
ARCHIVE_FORMATS = (BookFormat.CBZ, BookFormat.CBR, BookFormat.CB7)
PAGE_BASED_FORMATS = (*ARCHIVE_FORMATS, BookFormat.IMAGE_FOLDER)


class MetadataSource(str, enum.Enum):
    EMBEDDED = "embedded"
    ENRICHED = "enriched"
    MANUAL = "manual"


class CollectionType(str, enum.Enum):
    MANUAL = "manual"
    SMART = "smart"


class BookEditionType(str, enum.Enum):
    # A single numbered issue — the default and the vast majority of this
    # library. Never auto-reclassified once source == MANUAL (see
    # Book.edition_type's own docstring).
    ISSUE = "issue"
    # A trade paperback/omnibus/deluxe edition/etc. that collects several
    # issues under one file — auto-detected from filename patterns a
    # single issue wouldn't have ("v01", "TPB", "Omnibus", ...), see
    # kodex/acquire/sorting/comicinfo_writer.py's detect_edition_type. Kept separate
    # from a series' regular issue list (app/api/routes/series.py) so it
    # doesn't collide in reading order with the individual issues it
    # collects — they're very often the same Book.number by coincidence
    # (e.g. "v02" and issue "002" of the same series).
    COLLECTED = "collected"


class RequestMediaType(str, enum.Enum):
    SERIES = "series"
    EBOOK = "ebook"
    MANGA = "manga"


class RequestStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    FULFILLED = "fulfilled"
    REJECTED = "rejected"


class PanelStatus(str, enum.Enum):
    """Per-book Guided View detection status — see app/panels/service.py."""

    PENDING = "pending"
    DONE = "done"
    FAILED = "failed"
    # Format isn't page-based (EPUB/PDF) or Guided View is globally
    # disabled (settings.guided_view_enabled) — see BookPanelStatus.
    UNSUPPORTED = "unsupported"


class AIProvider(str, enum.Enum):
    """Which LLM API settings.ai_api_key/ai_model are for — see app/ai/
    for the per-provider client modules. Matches ReadMeABook's BookDate
    feature's provider set minus its "custom"/local-LLM option (not
    requested for Kodex's first cut)."""

    OPENAI = "openai"
    CLAUDE = "claude"
    GEMINI = "gemini"


class AISuggestionStatus(str, enum.Enum):
    """Lifecycle of one cached AIRecommendation row — see app/ai/
    recommendations.py and the /ai/recommendations* routes."""

    SUGGESTED = "suggested"
    # Swiped/clicked right — a Request was created from it (see
    # AIRecommendation.request_id).
    REQUESTED = "requested"
    # Swiped/clicked left — excluded from future generations for this user
    # (see recommendations.py's _already_seen_titles) without cluttering
    # the requests queue.
    DISMISSED = "dismissed"


class PageFlagReason(str, enum.Enum):
    """Why a reader flagged a page — see app/models/page_flag.py."""

    BLANK = "blank"
    DUPLICATE = "duplicate"
    CORRUPT = "corrupt"
    OTHER = "other"


class PageFlagResolution(str, enum.Enum):
    """An admin's verdict on a flagged page (B6) — see the /resolve
    route. DELETED hides the page from the reader (see ImageReader.tsx's
    handling of Book.deleted_page_indices) without ever touching the
    source archive file itself (see page_flag.py's own docstring for
    why); KEPT just closes out the flag with no reader-facing effect.
    """

    DELETED = "deleted"
    KEPT = "kept"


class SortingStatus(str, enum.Enum):
    # Needs a human call — kodex/acquire/sorting/classifier.py wasn't confident
    # enough to set resolved_type on its own.
    PENDING = "pending"
    # Has a resolved_type (auto-detected with high confidence, or set by
    # an admin in the review queue) and is ready for /sorting/apply to
    # move it.
    RESOLVED = "resolved"
    # Moved to its destination library. Terminal state.
    APPLIED = "applied"
    # Admin chose to leave this one where it is. Terminal state.
    SKIPPED = "skipped"


class DownloadSource(str, enum.Enum):
    """Where a Download's link/search-result came from — see
    app/models/download.py. Purely informational (shown in the admin
    downloads list), no behavior branches on it directly."""

    PROWLARR = "prowlarr"
    ANNAS_ARCHIVE = "annas_archive"
    GETCOMICS = "getcomics"
    MANUAL = "manual"


class DownloadClientType(str, enum.Enum):
    """Which backend actually fetches a Download — see kodex/acquire/clients/
    manager.py's dispatch. Named *Type to avoid colliding with
    kodex/acquire/clients/base.py's DownloadClient ABC (the actual client
    implementations this enum picks between). DIRECT_HTTP covers Anna's
    Archive/GetComics (a plain file URL, no torrent/nzb protocol
    involved) — streamed straight into the target library by the worker
    itself, no external download client at all."""

    QBITTORRENT = "qbittorrent"
    SABNZBD = "sabnzbd"
    DIRECT_HTTP = "direct_http"


class DownloadStatus(str, enum.Enum):
    QUEUED = "queued"
    DOWNLOADING = "downloading"
    COMPLETED = "completed"
    FAILED = "failed"
    # A source result that can't be auto-fetched (e.g. an Anna's Archive
    # gated link) — surfaced in the admin downloads list for manual
    # retrieval, then landed via the B7 library-upload endpoint. See
    # kodex/acquire/clients/annas_archive.py.
    NEEDS_REVIEW = "needs_review"
