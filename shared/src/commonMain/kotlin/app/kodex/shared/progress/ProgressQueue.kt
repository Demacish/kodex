package app.kodex.shared.progress

import app.kodex.shared.api.KodexApi
import app.kodex.shared.api.KodexApiException
import app.kodex.shared.api.ReadingProgressIn

/** A reading position the app hasn't sent yet. [seq] is this device's report number. */
data class Outgoing(
    val id: Long,
    val bookId: Int,
    val position: String?,
    val locatorKind: String?,
    val percent: Double,
    val finished: Boolean,
    val chapter: String?,
    val seq: Long,
    val at: String,
)

/** The outbox: positions are written here first, so reading works without a network. */
interface Outbox {
    /** Oldest first. */
    suspend fun pending(): List<Outgoing>

    suspend fun sent(id: Long)
}

data class FlushResult(val sent: Int, val dropped: Int, val left: Int, val unauthorized: Boolean = false)

/**
 * Sends the outbox in order. The server journals each report and makes the newest per device
 * (by [Outgoing.seq]) the book's position, so a retry of a report it already has is harmless.
 * A network failure stops the flush with the rest left for next time; a book the server no
 * longer has drops its reports; a revoked key stops everything.
 */
class ProgressSender(
    private val api: KodexApi,
    private val outbox: Outbox,
    private val deviceId: String,
    private val deviceName: String,
) {
    suspend fun flush(): FlushResult {
        val pending = outbox.pending()
        var sent = 0
        var dropped = 0
        for ((index, item) in pending.withIndex()) {
            try {
                api.saveProgress(item.bookId, item.toIn())
                outbox.sent(item.id)
                sent += 1
            } catch (e: KodexApiException) {
                when {
                    e.unauthorized -> return FlushResult(sent, dropped, pending.size - index, unauthorized = true)
                    e.status == 404 || e.status == 403 || e.status == 422 -> {
                        outbox.sent(item.id)
                        dropped += 1
                    }
                    else -> return FlushResult(sent, dropped, pending.size - index)
                }
            } catch (e: kotlinx.coroutines.CancellationException) {
                throw e
            } catch (e: Exception) {
                return FlushResult(sent, dropped, pending.size - index)
            }
        }
        return FlushResult(sent, dropped, 0)
    }

    private fun Outgoing.toIn() = ReadingProgressIn(
        position = position,
        locatorKind = locatorKind,
        progressPercent = percent,
        isFinished = finished,
        chapter = chapter,
        deviceId = deviceId,
        deviceName = deviceName,
        clientSeq = seq,
        clientAt = at,
    )
}

