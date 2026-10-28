package app.kodex.reader

import android.content.Context
import app.kodex.data.Position
import app.kodex.data.Positions
import app.kodex.download.Downloads
import app.kodex.sync.SyncWorker
import app.kodex.widget.ContinueReadingWidget
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

/**
 * Saves where the reader is, a moment after it stops moving (and at once when it closes),
 * then asks for the positions to be sent. Runs in the app's scope, so a closing reader's last
 * position isn't lost.
 */
class ProgressReporter(
    private val context: Context,
    private val bookId: Int,
    private val positions: Positions,
    private val downloads: Downloads,
    private val scope: CoroutineScope,
) {
    private var pending: Position? = null
    private var saved: Position? = null
    private var job: Job? = null

    fun report(at: Position) {
        if (at == saved) return
        pending = at
        job?.cancel()
        job = scope.launch {
            delay(1_500)
            save()
        }
    }

    /** The reader is closing (or going to the background). */
    fun flush() {
        job?.cancel()
        scope.launch { save() }
    }

    private suspend fun save() {
        val at = pending ?: return
        pending = null
        saved = at
        positions.record(bookId, at)
        SyncWorker.sendPositions(context)
        ContinueReadingWidget.refresh(context)
        if (at.finished) downloads.fetchNext()
    }
}
