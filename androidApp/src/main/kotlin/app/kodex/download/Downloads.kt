package app.kodex.download

import android.content.Context
import androidx.work.BackoffPolicy
import androidx.work.Constraints
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.workDataOf
import app.kodex.data.SettingsStore
import app.kodex.data.db.BookEntity
import app.kodex.data.db.DownloadEntity
import app.kodex.data.db.DownloadKinds
import app.kodex.data.db.DownloadState
import app.kodex.data.db.KodexDatabase
import java.io.File
import java.util.concurrent.TimeUnit

/** Book formats the device reads from the file itself; the others come as pages. */
val FILE_FORMATS = setOf("epub", "pdf", "cbz")

/**
 * Downloads on the device, under `files/books/<id>/`: `book.<format>` for a file, `pages/` for
 * pages. Each runs as unique work (`download-<id>`), on Wi-Fi only when the setting says so.
 */
class Downloads(private val context: Context, private val db: KodexDatabase, private val settings: SettingsStore) {
    private val dao = db.downloads()
    private val root = File(context.filesDir, "books")

    fun dir(bookId: Int) = File(root, bookId.toString())

    fun file(bookId: Int, format: String) = File(dir(bookId), "book.$format")

    fun pages(bookId: Int) = File(dir(bookId), "pages")

    suspend fun request(book: BookEntity, automatic: Boolean = false) {
        val existing = dao.get(book.id)
        if (existing?.state == DownloadState.DONE) return
        val kind = if (book.format in FILE_FORMATS) DownloadKinds.FILE else DownloadKinds.PAGES
        dao.save(
            DownloadEntity(book.id, DownloadState.QUEUED, kind, existing?.bytes ?: 0, book.fileSize, null, null,
                automatic = existing?.automatic ?: automatic, requestedAt = System.currentTimeMillis(), pageSizes = existing?.pageSizes),
        )
        enqueue(book.id, settings.current().wifiOnly)
    }

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

    /** Queued downloads wait for the new network rule (Wi-Fi only, or any). */
    suspend fun requeueAll() {
        val wifiOnly = settings.current().wifiOnly
        dao.all().filter { it.state == DownloadState.QUEUED || it.state == DownloadState.RUNNING || it.state == DownloadState.FAILED }
            .forEach {
                WorkManager.getInstance(context).cancelUniqueWork(name(it.bookId))
                dao.update(it.bookId, DownloadState.QUEUED, it.bytes, it.total, null)
                enqueue(it.bookId, wifiOnly)
            }
    }

    suspend fun remove(bookId: Int) {
        WorkManager.getInstance(context).cancelUniqueWork(name(bookId))
        dao.delete(bookId)
        dir(bookId).deleteRecursively()
    }

    /** Files of books the server no longer has. */
    suspend fun prune() {
        dao.orphans().forEach { remove(it) }
        root.listFiles()?.filter { dir -> dir.name.toIntOrNull()?.let { dao.get(it) } == null }?.forEach { it.deleteRecursively() }
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
        root.deleteRecursively()
    }

    companion object {
        const val TAG = "download"

        fun name(bookId: Int) = "download-$bookId"
    }
}
