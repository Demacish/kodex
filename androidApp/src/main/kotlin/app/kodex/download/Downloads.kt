package app.kodex.download

import android.content.Context
import android.os.Environment
import android.os.StatFs
import androidx.work.BackoffPolicy
import androidx.work.Constraints
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkInfo
import androidx.work.WorkManager
import androidx.work.workDataOf
import app.kodex.data.SettingsStore
import app.kodex.data.StorageTarget
import app.kodex.data.db.BookEntity
import app.kodex.data.db.DownloadEntity
import app.kodex.data.db.DownloadKinds
import app.kodex.data.db.DownloadState
import app.kodex.data.db.KodexDatabase
import java.io.File
import java.time.Instant
import java.time.OffsetDateTime
import java.util.concurrent.TimeUnit
import kotlinx.coroutines.flow.first

/** Book formats the device reads from the file itself; the others come as pages. */
val FILE_FORMATS = setOf("epub", "pdf", "cbz")

/**
 * Downloads on the device, under `books/<id>/` in the app's own storage or on the memory card:
 * `book.<format>` for a file, `pages/` for pages. Each runs as unique work (`download-<id>`), on
 * Wi-Fi only when the setting says so, and takes its turn in the queue ([DownloadWorker]: as
 * many at once as the setting allows, in the queue's order). A paused one keeps what came.
 */
class Downloads(private val context: Context, private val db: KodexDatabase, private val settings: SettingsStore) {
    private val dao = db.downloads()
    private val internal = File(context.filesDir, "books")

    /** The memory card's books folder, when the device has a card in. */
    fun card(): File? = context.getExternalFilesDirs(null).drop(1)
        .firstOrNull { it != null && Environment.getExternalStorageState(it) == Environment.MEDIA_MOUNTED && Environment.isExternalStorageRemovable(it) }
        ?.let { File(it, "books") }

    /** Where a book's download is: on the card when it went there, else in the app's storage. */
    fun dir(bookId: Int): File = card()?.let { File(it, bookId.toString()) }?.takeIf { it.exists() } ?: File(internal, bookId.toString())

    /** Where a download goes. */
    fun dir(download: DownloadEntity): File =
        (if (download.onCard) card() else null)?.let { File(it, download.bookId.toString()) } ?: File(internal, download.bookId.toString())

    fun file(bookId: Int, format: String) = File(dir(bookId), "book.$format")

    fun pages(bookId: Int) = File(dir(bookId), "pages")

    fun file(download: DownloadEntity, format: String) = File(dir(download), "book.$format")

    fun pages(download: DownloadEntity) = File(dir(download), "pages")

    /** Room left where new downloads go. */
    fun freeBytes(target: StorageTarget): Long? {
        val root = if (target == StorageTarget.CARD) card() ?: return null else internal
        root.mkdirs()
        return runCatching { StatFs(root.path).availableBytes }.getOrNull()
    }

    /** Asks for [book]; [first] puts it at the front of the queue. */
    suspend fun request(book: BookEntity, automatic: Boolean = false, first: Boolean = false) {
        val existing = dao.get(book.id)
        if (existing?.state == DownloadState.DONE) return
        val prefs = settings.current()
        val kind = if (book.format in FILE_FORMATS) DownloadKinds.FILE else DownloadKinds.PAGES
        val position = existing?.position?.takeIf { !first } ?: if (first) dao.firstPosition() else dao.lastPosition()
        dao.save(
            DownloadEntity(
                book.id, DownloadState.QUEUED, kind, existing?.bytes ?: 0, book.fileSize, null, null,
                automatic = existing?.automatic ?: automatic, requestedAt = System.currentTimeMillis(), pageSizes = existing?.pageSizes,
                position = position, attempts = 0, finishedAt = null,
                // What came already stays where it is.
                onCard = existing?.onCard ?: (prefs.storage == StorageTarget.CARD && card() != null),
            ),
        )
        enqueue(book.id, prefs.wifiOnly)
    }

    /** Every book of [books] that isn't on the device yet, in their order. */
    suspend fun requestAll(books: List<BookEntity>) = books.forEach { request(it) }

    fun enqueue(bookId: Int, wifiOnly: Boolean) {
        val request = OneTimeWorkRequestBuilder<DownloadWorker>()
            .setInputData(workDataOf(DownloadWorker.BOOK_ID to bookId))
            .setConstraints(
                Constraints.Builder()
                    .setRequiredNetworkType(if (wifiOnly) NetworkType.UNMETERED else NetworkType.CONNECTED)
                    .setRequiresStorageNotLow(true)
                    .build(),
            )
            .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 30, TimeUnit.SECONDS)
            .addTag(TAG)
            .build()
        WorkManager.getInstance(context).enqueueUniqueWork(name(bookId), ExistingWorkPolicy.KEEP, request)
    }

    /** Stops a download where it is; what came is kept for when it goes on. */
    suspend fun pause(bookId: Int) {
        dao.setState(bookId, DownloadState.PAUSED)
        WorkManager.getInstance(context).cancelUniqueWork(name(bookId))
    }

    suspend fun resume(bookId: Int) {
        dao.requeue(bookId)
        enqueue(bookId, settings.current().wifiOnly)
    }

    /** Another try at a failed download, from the start of its attempts. */
    suspend fun retry(bookId: Int) = resume(bookId)

    suspend fun pauseAll() {
        dao.all().filter { it.state == DownloadState.QUEUED || it.state == DownloadState.RUNNING }.forEach { pause(it.bookId) }
    }

    suspend fun resumeAll() {
        dao.all().filter { it.state == DownloadState.PAUSED }.forEach { resume(it.bookId) }
    }

    /** First in the queue. */
    suspend fun moveToFront(bookId: Int) = dao.setPosition(bookId, dao.firstPosition())

    /** The queue in this order. */
    suspend fun reorder(bookIds: List<Int>) = bookIds.forEachIndexed { index, id -> dao.setPosition(id, index + 1L) }

    /** Queued downloads wait for the new network rule (Wi-Fi only, or any). */
    suspend fun requeueAll() {
        val wifiOnly = settings.current().wifiOnly
        dao.all().filter { it.state == DownloadState.QUEUED || it.state == DownloadState.RUNNING || it.state == DownloadState.FAILED }
            .forEach {
                WorkManager.getInstance(context).cancelUniqueWork(name(it.bookId))
                dao.requeue(it.bookId)
                enqueue(it.bookId, wifiOnly)
            }
    }

    /**
     * A download that says it is running but has no work behind it (the work was lost) goes back
     * in the queue, so it doesn't hold a turn for ever.
     */
    suspend fun recover() {
        val manager = WorkManager.getInstance(context)
        val wifiOnly = settings.current().wifiOnly
        dao.all().filter { it.state == DownloadState.RUNNING || it.state == DownloadState.QUEUED }.forEach { download ->
            val alive = manager.getWorkInfosForUniqueWorkFlow(name(download.bookId)).first()
                .any { it.state == WorkInfo.State.RUNNING || it.state == WorkInfo.State.ENQUEUED || it.state == WorkInfo.State.BLOCKED }
            if (!alive) {
                dao.requeue(download.bookId)
                enqueue(download.bookId, wifiOnly)
            }
        }
    }

    suspend fun remove(bookId: Int) {
        WorkManager.getInstance(context).cancelUniqueWork(name(bookId))
        dao.delete(bookId)
        File(internal, bookId.toString()).deleteRecursively()
        card()?.let { File(it, bookId.toString()).deleteRecursively() }
    }

    /** Files of books the server no longer has. */
    suspend fun prune() {
        dao.orphans().forEach { remove(it) }
        listOfNotNull(internal, card()).forEach { root ->
            root.listFiles()?.filter { dir -> dir.name.toIntOrNull()?.let { dao.get(it) } == null }?.forEach { it.deleteRecursively() }
        }
    }

    /** "Clean up": downloads of books finished more than the setting's days ago go. */
    suspend fun cleanUp(now: Instant = Instant.now()) {
        val days = settings.current().cleanupDays
        if (days <= 0) return
        val before = now.minusSeconds(days * 86_400L)
        dao.finishedDownloads().forEach { finished ->
            val readAt = runCatching { OffsetDateTime.parse(finished.readAt).toInstant() }.getOrNull() ?: return@forEach
            if (readAt.isBefore(before)) remove(finished.bookId)
        }
    }

    /** "Download the next ones": the next unread books after each one being read here. */
    suspend fun fetchNext() {
        val count = settings.current().autoNext
        if (count <= 0) return
        val catalog = db.catalog()
        catalog.readingDownloaded().forEach { reading ->
            catalog.nextToFetch(reading, count).forEach { request(it, automatic = true) }
        }
    }

    /** Everything goes: logging out, or another account. */
    suspend fun clearAll() {
        WorkManager.getInstance(context).cancelAllWorkByTag(TAG)
        dao.clearAll()
        internal.deleteRecursively()
        card()?.deleteRecursively()
    }

    companion object {
        const val TAG = "download"

        /** Failed attempts before a download waits for the user. */
        const val ATTEMPTS = 5

        fun name(bookId: Int) = "download-$bookId"
    }
}
