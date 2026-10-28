package app.kodex.data

import app.kodex.data.db.KodexDatabase
import app.kodex.data.db.OutboxEntity
import app.kodex.data.db.ProgressEntity
import app.kodex.data.db.SyncStateEntity
import app.kodex.shared.progress.Outbox
import app.kodex.shared.progress.Outgoing
import androidx.room3.withWriteTransaction
import java.time.Instant

/** Where a reader is in a book, in the server's terms (kodex/reading/positions.py). */
data class Position(
    val position: String?,
    val locatorKind: String?,
    val percent: Double,
    val finished: Boolean,
    val chapter: String? = null,
)

/**
 * Reading positions on the device. A position is saved here first, with the next report number
 * and the time, and goes to the server from the outbox (shared ProgressSender) when there is a
 * network, so reading works the same offline.
 */
class Positions(private val db: KodexDatabase, private val deviceName: () -> String) : Outbox {
    private val catalog = db.catalog()
    private val state = db.state()

    suspend fun record(bookId: Int, at: Position) {
        val now = Instant.now().toString()
        db.withWriteTransaction {
            val saved = state.state() ?: SyncStateEntity(0, 0, 0, "", null, 0)
            val seq = saved.lastSeq + 1
            state.save(saved.copy(lastSeq = seq))
            state.queue(
                OutboxEntity(bookId = bookId, position = at.position, locatorKind = at.locatorKind, percent = at.percent,
                    finished = at.finished, chapter = at.chapter, seq = seq, at = now),
            )
            catalog.upsertProgress(
                listOf(ProgressEntity(bookId, at.position, at.locatorKind, at.percent, at.finished, at.chapter, now, deviceName())),
            )
        }
    }

    override suspend fun pending(): List<Outgoing> = state.pending().map {
        Outgoing(it.id, it.bookId, it.position, it.locatorKind, it.percent, it.finished, it.chapter, it.seq, it.at)
    }

    override suspend fun sent(id: Long) = state.sent(id)
}
