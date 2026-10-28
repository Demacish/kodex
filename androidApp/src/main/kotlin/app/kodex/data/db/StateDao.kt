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

    @Query("UPDATE downloads SET pageSizes = :sizes WHERE bookId = :bookId")
    suspend fun setPageSizes(bookId: Int, sizes: String?)

    @Query("UPDATE downloads SET sha256 = :sha256 WHERE bookId = :bookId")
    suspend fun setSha256(bookId: Int, sha256: String)

    @Query("DELETE FROM downloads WHERE bookId = :bookId") suspend fun delete(bookId: Int)

    @Query("DELETE FROM downloads") suspend fun clearAll()

    @Query("SELECT bookId FROM downloads WHERE bookId NOT IN (SELECT id FROM books)") suspend fun orphans(): List<Int>

    @Query("SELECT * FROM downloads") suspend fun all(): List<DownloadEntity>

    @Query(
        """SELECT d.*, b.title AS title, b.format AS format FROM downloads d JOIN books b ON b.id = d.bookId
           ORDER BY d.state = 'DONE', d.requestedAt DESC""",
    )
    fun list(): Flow<List<DownloadRow>>

    @Query("SELECT coalesce(sum(bytes), 0) FROM downloads WHERE state = 'DONE'") fun usedBytes(): Flow<Long>
}

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
    val title: String,
    val format: String,
)
