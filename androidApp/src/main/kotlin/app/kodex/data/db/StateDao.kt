package app.kodex.data.db

import androidx.room3.Dao
import androidx.room3.Insert
import androidx.room3.Query
import androidx.room3.Upsert
import kotlinx.coroutines.flow.Flow

@Dao
interface StateDao {
    @Query("SELECT * FROM sync_state WHERE id = 0") suspend fun state(): SyncStateEntity?

    @Query("SELECT * FROM sync_state WHERE id = 0") fun observe(): Flow<SyncStateEntity?>

    @Upsert suspend fun save(state: SyncStateEntity)

    @Insert suspend fun queue(item: OutboxEntity): Long

    @Query("SELECT * FROM outbox ORDER BY id") suspend fun pending(): List<OutboxEntity>

    @Query("SELECT count(*) FROM outbox") fun pendingCount(): Flow<Int>

    @Query("SELECT EXISTS(SELECT 1 FROM outbox WHERE bookId = :bookId)") suspend fun hasPending(bookId: Int): Boolean

    @Query("DELETE FROM outbox WHERE id = :id") suspend fun sent(id: Long)

    @Query("DELETE FROM outbox") suspend fun clearOutbox()

    @Query("DELETE FROM sync_state") suspend fun clearState()
}

@Dao
interface DownloadDao {
    @Upsert suspend fun save(download: DownloadEntity)

    @Query("SELECT * FROM downloads WHERE bookId = :bookId") suspend fun get(bookId: Int): DownloadEntity?

    @Query("SELECT * FROM downloads WHERE bookId = :bookId") fun observe(bookId: Int): Flow<DownloadEntity?>

    @Query("UPDATE downloads SET state = :state, bytes = :bytes, total = :total, error = :error WHERE bookId = :bookId")
    suspend fun update(bookId: Int, state: DownloadState, bytes: Long, total: Long, error: String?)

    /** How far a download is; one paused (or removed) meanwhile stays as it is. */
    @Query(
        """UPDATE downloads SET state = 'RUNNING', bytes = :bytes, total = :total, error = NULL
           WHERE bookId = :bookId AND state IN ('QUEUED', 'RUNNING')""",
    )
    suspend fun progress(bookId: Int, bytes: Long, total: Long)

    @Query(
        """UPDATE downloads SET state = 'DONE', bytes = :bytes, total = :bytes, error = NULL, attempts = 0, finishedAt = :at
           WHERE bookId = :bookId""",
    )
    suspend fun done(bookId: Int, bytes: Long, at: Long)

    /** A failed attempt, counted; a download the user paused meanwhile stays paused. */
    @Query(
        """UPDATE downloads SET state = 'FAILED', error = :error, attempts = attempts + 1
           WHERE bookId = :bookId AND state != 'PAUSED'""",
    )
    suspend fun fail(bookId: Int, error: String)

    @Query("UPDATE downloads SET state = :state WHERE bookId = :bookId") suspend fun setState(bookId: Int, state: DownloadState)

    /** Back in the queue, from the start of its attempts. */
    @Query("UPDATE downloads SET state = 'QUEUED', error = NULL, attempts = 0 WHERE bookId = :bookId")
    suspend fun requeue(bookId: Int)

    @Query("UPDATE downloads SET position = :position WHERE bookId = :bookId") suspend fun setPosition(bookId: Int, position: Long)

    @Query("SELECT coalesce(max(position), 0) + 1 FROM downloads") suspend fun lastPosition(): Long

    @Query("SELECT coalesce(min(position), 0) - 1 FROM downloads") suspend fun firstPosition(): Long

    /** The downloads waiting or running, in the order they get to run: the running ones, then the queue. */
    @Query(
        """SELECT bookId FROM downloads WHERE state IN ('QUEUED', 'RUNNING')
           ORDER BY state = 'RUNNING' DESC, position, requestedAt""",
    )
    fun turns(): Flow<List<Int>>

    @Query("UPDATE downloads SET pageSizes = :sizes WHERE bookId = :bookId")
    suspend fun setPageSizes(bookId: Int, sizes: String?)

    @Query("UPDATE downloads SET sha256 = :sha256 WHERE bookId = :bookId")
    suspend fun setSha256(bookId: Int, sha256: String)

    @Query("DELETE FROM downloads WHERE bookId = :bookId") suspend fun delete(bookId: Int)

    @Query("DELETE FROM downloads") suspend fun clearAll()

    @Query("SELECT bookId FROM downloads WHERE bookId NOT IN (SELECT id FROM books)") suspend fun orphans(): List<Int>

    @Query("SELECT * FROM downloads") suspend fun all(): List<DownloadEntity>

    /** Downloaded books that are finished, and when they were last read: what "clean up" looks at. */
    @Query(
        """SELECT d.bookId AS bookId, p.readAt AS readAt FROM downloads d JOIN progress p ON p.bookId = d.bookId
           WHERE d.state = 'DONE' AND p.finished""",
    )
    suspend fun finishedDownloads(): List<FinishedDownload>

    @Query(
        """SELECT d.*, b.title AS title, b.format AS format, b.number AS number, s.title AS seriesTitle,
                  l.libraryType AS libraryType
           FROM downloads d JOIN books b ON b.id = d.bookId LEFT JOIN series s ON s.id = b.seriesId
           LEFT JOIN libraries l ON l.id = b.libraryId
           ORDER BY d.position, d.requestedAt""",
    )
    fun list(): Flow<List<DownloadRow>>

    @Query("SELECT coalesce(sum(bytes), 0) FROM downloads WHERE state = 'DONE'") fun usedBytes(): Flow<Long>
}

data class FinishedDownload(val bookId: Int, val readAt: String)

data class DownloadRow(
    val bookId: Int,
    val state: DownloadState,
    val kind: String,
    val bytes: Long,
    val total: Long,
    val sha256: String?,
    val error: String?,
    val automatic: Boolean,
    val requestedAt: Long,
    val pageSizes: String?,
    val position: Long,
    val attempts: Int,
    val finishedAt: Long?,
    val onCard: Boolean,
    val title: String,
    val format: String,
    val number: Double?,
    val seriesTitle: String?,
    val libraryType: String?,
)

@Dao
interface BookmarkDao {
    @Upsert suspend fun save(bookmark: BookmarkEntity)

    /** A book's bookmarks, in reading order (the removed ones not yet sent left out). */
    @Query(
        """SELECT * FROM bookmarks WHERE bookId = :bookId AND (pending IS NULL OR pending != 'delete')
           ORDER BY percent, createdAt""",
    )
    fun of(bookId: Int): Flow<List<BookmarkEntity>>

    @Query("SELECT * FROM bookmarks WHERE id = :id") suspend fun get(id: String): BookmarkEntity?

    @Query("SELECT * FROM bookmarks WHERE pending IS NOT NULL") suspend fun pending(): List<BookmarkEntity>

    @Query("UPDATE bookmarks SET pending = 'delete' WHERE id = :id") suspend fun markDeleted(id: String)

    @Query("UPDATE bookmarks SET pending = NULL WHERE id = :id") suspend fun sent(id: String)

    @Query("DELETE FROM bookmarks WHERE id = :id") suspend fun delete(id: String)

    /** The server's bookmarks replace the ones it already had; those made or removed here stay. */
    @Query("DELETE FROM bookmarks WHERE pending IS NULL") suspend fun clearSent()

    @Query("DELETE FROM bookmarks") suspend fun clearAll()
}
