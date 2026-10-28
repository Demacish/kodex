package app.kodex.data.db

import androidx.room3.Entity
import androidx.room3.Index
import androidx.room3.PrimaryKey

// The catalog as the server last sent it (GET /api/sync/changes), what this device has read and
// not yet sent, and what it has downloaded. Ids are the server's.

@Entity(tableName = "libraries")
data class LibraryEntity(@PrimaryKey val id: Int, val name: String, val libraryType: String)

@Entity(tableName = "series", indices = [Index("libraryId")])
data class SeriesEntity(
    @PrimaryKey val id: Int,
    val libraryId: Int,
    val title: String,
    val startYear: Int?,
    val publisher: String?,
    val summary: String?,
    val bookCount: Int,
    val following: Boolean,
)

@Entity(tableName = "books", indices = [Index("seriesId"), Index("libraryId")])
data class BookEntity(
    @PrimaryKey val id: Int,
    val libraryId: Int,
    val seriesId: Int?,
    val title: String,
    val sortTitle: String,
    val number: Double?,
    val format: String,
    val fileSize: Long,
    val pageCount: Int?,
    val editionType: String,
    val authors: String,
    val summary: String?,
    val publishedYear: Int?,
    val language: String?,
)

@Entity(tableName = "collections")
data class CollectionEntity(@PrimaryKey val id: Int, val name: String, val collectionType: String)

@Entity(tableName = "collection_books", primaryKeys = ["collectionId", "position"], indices = [Index("bookId")])
data class CollectionBookEntity(val collectionId: Int, val position: Int, val bookId: Int)

/** A book's reading position: the server's, or one read here (still in the outbox, or sent). */
@Entity(tableName = "progress")
data class ProgressEntity(
    @PrimaryKey val bookId: Int,
    val position: String?,
    val locatorKind: String?,
    val percent: Double,
    val finished: Boolean,
    val chapter: String?,
    /** ISO 8601. */
    val readAt: String,
    val deviceName: String?,
)

/** A position read on this device, waiting to be sent (oldest first). */
@Entity(tableName = "outbox", indices = [Index("bookId")])
data class OutboxEntity(
    @PrimaryKey(autoGenerate = true) val id: Long = 0,
    val bookId: Int,
    val position: String?,
    val locatorKind: String?,
    val percent: Double,
    val finished: Boolean,
    val chapter: String?,
    val seq: Long,
    val at: String,
)

@Entity(tableName = "sync_state")
data class SyncStateEntity(
    @PrimaryKey val id: Int = 0,
    val catalogCursor: Long,
    val progressCursor: Long,
    /** The account the catalog belongs to (Session.owner). */
    val owner: String,
    val syncedAt: Long?,
    /** This device's report numbers for the server's journal (client_seq). */
    val lastSeq: Long,
)

enum class DownloadState { QUEUED, RUNNING, DONE, FAILED }

/**
 * A downloaded (or downloading) book. [kind] says what is on disk: the book's file, verified
 * against the server's SHA-256, or its pages one by one (archives the device can't open itself).
 */
@Entity(tableName = "downloads")
data class DownloadEntity(
    @PrimaryKey val bookId: Int,
    val state: DownloadState,
    val kind: String,
    val bytes: Long,
    val total: Long,
    val sha256: String?,
    val error: String?,
    /** Fetched by "download the next ones", not by the user. */
    val automatic: Boolean,
    val requestedAt: Long,
    /** The pages' [width, height] as the server measured them (JSON), for the reader's layout. */
    val pageSizes: String?,
)

object DownloadKinds {
    const val FILE = "file"
    const val PAGES = "pages"
}
