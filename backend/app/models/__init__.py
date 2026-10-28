"""Import every model so Base.metadata is fully populated for
`create_all()` (dev/tests) and for Alembic's autogenerate (production).
"""

from app.models.ai_recommendation import AIRecommendation
from app.models.book import Book
from app.models.collection import Collection, collection_books
from app.models.content_index import ContentIndexEntry
from app.models.download import Download
from app.models.kosync import KosyncProgress
from app.models.library import Library
from app.models.metadata import BookMetadata
from app.models.page_flag import BookPageFlag
from app.models.panel import BookPagePanel, BookPanelStatus
from app.models.reading_progress import ReadingProgress
from app.models.release_event import SeriesReleaseEvent
from app.models.request import Request
from app.models.scheduler_state import SchedulerState
from app.models.series import Series
from app.models.sorting import SortingItem
from app.models.story_arc import StoryArc, StoryArcIssue
from app.models.user import User
from kodex.core.auth.models import ApiKey, LoginFailure, OidcLogin, UserSession
from kodex.core.sync_log import SyncLog
from kodex.jobs.models import JobResult
from kodex.library.models import BookFileHash
from kodex.matching.models import MatchReview, ProviderCache, ProviderRateState, SeriesAlias, SeriesExternalId
from kodex.reading.models import ReadingEvent
from kodex.reading.trackers.models import TrackerAccount, TrackerLink

__all__ = [
    "AIRecommendation",
    "Book",
    "ApiKey",
    "BookFileHash",
    "JobResult",
    "LoginFailure",
    "OidcLogin",
    "ReadingEvent",
    "SyncLog",
    "TrackerAccount",
    "TrackerLink",
    "Collection",
    "collection_books",
    "ContentIndexEntry",
    "Download",
    "KosyncProgress",
    "Library",
    "BookMetadata",
    "BookPageFlag",
    "BookPagePanel",
    "BookPanelStatus",
    "ReadingProgress",
    "SeriesReleaseEvent",
    "Request",
    "SchedulerState",
    "Series",
    "SortingItem",
    "StoryArc",
    "StoryArcIssue",
    "User",
    "UserSession",
    "MatchReview",
    "ProviderCache",
    "ProviderRateState",
    "SeriesAlias",
    "SeriesExternalId",
]
