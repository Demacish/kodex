package app.kodex.download

import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.Context
import android.content.pm.ServiceInfo
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.work.CoroutineWorker
import androidx.work.ForegroundInfo
import androidx.work.WorkerParameters
import app.kodex.R
import app.kodex.account.AccountStore
import app.kodex.data.db.DownloadKinds
import app.kodex.data.db.DownloadState
import app.kodex.data.db.KodexDatabase
import app.kodex.shared.api.KodexApi
import app.kodex.shared.api.KodexApiException
import app.kodex.shared.api.KodexJson
import app.kodex.shared.api.PageDimensions
import app.kodex.sync.ApiProvider
import java.io.IOException
import kotlinx.coroutines.CancellationException
import org.koin.core.component.KoinComponent
import org.koin.core.component.inject

/** Downloads one book, with a notification while it runs (a foreground job). */
class DownloadWorker(context: Context, params: WorkerParameters) : CoroutineWorker(context, params), KoinComponent {
    private val db: KodexDatabase by inject()
    private val accounts: AccountStore by inject()
    private val apis: ApiProvider by inject()
    private val downloads: Downloads by inject()
    private val fetcher: Fetcher by inject()

    override suspend fun doWork(): Result {
        val bookId = inputData.getInt(BOOK_ID, -1)
        val dao = db.downloads()
        val download = dao.get(bookId) ?: return Result.success()
        val book = db.catalog().bookNow(bookId) ?: return Result.success().also { downloads.remove(bookId) }
        val session = accounts.current() ?: return Result.failure()
        val api = apis.api(session)
        runCatching { setForeground(foreground(book.title, 0)) }
        dao.update(bookId, DownloadState.RUNNING, download.bytes, download.total, null)
        return try {
            when (download.kind) {
                DownloadKinds.FILE -> {
                    val digest = api.digest(bookId)
                    dao.update(bookId, DownloadState.RUNNING, download.bytes, digest.size, null)
                    fetcher.file(api.fileUrl(bookId), session.key, downloads.file(bookId, book.format), digest) { bytes ->
                        dao.update(bookId, DownloadState.RUNNING, bytes, digest.size, null)
                        progress(book.title, bytes, digest.size)
                    }
                    dao.setSha256(bookId, digest.sha256)
                    if (book.format == "cbz") dao.setPageSizes(bookId, runCatching { api.pageSizesJson(bookId) }.getOrNull())
                    dao.update(bookId, DownloadState.DONE, digest.size, digest.size, null)
                }
                else -> {
                    val sizes = api.pageSizesJson(bookId)
                    val count = book.pageCount ?: pageCount(sizes) ?: throw IOException("The server doesn't know the pages yet")
                    dao.setPageSizes(bookId, sizes)
                    var bytes = 0L
                    for (index in 0 until count) {
                        bytes += fetcher.page(api.pageUrl(bookId, index), session.key, downloads.pages(bookId), index)
                        dao.update(bookId, DownloadState.RUNNING, bytes, book.fileSize, null)
                        progress(book.title, index + 1L, count.toLong())
                    }
                    dao.update(bookId, DownloadState.DONE, bytes, bytes, null)
                }
            }
            Result.success()
        } catch (e: CancellationException) {
            throw e
        } catch (e: VerificationFailed) {
            failed(bookId, e)
            if (runAttemptCount < 2) Result.retry() else Result.failure()
        } catch (e: Refused) {
            failed(bookId, e)
            if (e.status >= 500 && runAttemptCount < 5) Result.retry() else Result.failure()
        } catch (e: KodexApiException) {
            failed(bookId, e)
            if (e.status >= 500 && runAttemptCount < 5) Result.retry() else Result.failure()
        } catch (e: IOException) {
            // The network went: what came is kept, and the rest comes when it is back.
            val now = dao.get(bookId)
            dao.update(bookId, DownloadState.QUEUED, now?.bytes ?: 0, now?.total ?: 0, null)
            Result.retry()
        }
    }

    private suspend fun failed(bookId: Int, e: Exception) {
        val now = db.downloads().get(bookId)
        db.downloads().update(bookId, DownloadState.FAILED, now?.bytes ?: 0, now?.total ?: 0, e.message ?: e.javaClass.simpleName)
    }

    private suspend fun progress(title: String, done: Long, total: Long) {
        val percent = if (total > 0) (done * 100 / total).toInt() else 0
        runCatching { setForeground(foreground(title, percent)) }
    }

    private fun foreground(title: String, percent: Int): ForegroundInfo {
        val manager = applicationContext.getSystemService(NotificationManager::class.java)
        if (manager.getNotificationChannel(CHANNEL) == null) {
            manager.createNotificationChannel(
                NotificationChannel(CHANNEL, applicationContext.getString(R.string.downloads_channel), NotificationManager.IMPORTANCE_LOW),
            )
        }
        val notification = NotificationCompat.Builder(applicationContext, CHANNEL)
            .setSmallIcon(android.R.drawable.stat_sys_download)
            .setContentTitle(applicationContext.getString(R.string.downloading, title))
            .setProgress(100, percent, percent == 0)
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .build()
        val id = NOTIFICATION_BASE + inputData.getInt(BOOK_ID, 0) % 10_000
        return if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            ForegroundInfo(id, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC)
        } else {
            ForegroundInfo(id, notification)
        }
    }

    companion object {
        const val BOOK_ID = "book_id"
        const val CHANNEL = "downloads"
        private const val NOTIFICATION_BASE = 20_000
    }
}

/** The pages' sizes as the server measured them, to keep with the download; null while it hasn't. */
private suspend fun KodexApi.pageSizesJson(bookId: Int): String? {
    val dimensions = pageDimensions(bookId)
    if (dimensions.dimensions == null) return null
    return KodexJson.encodeToString(PageDimensions.serializer(), dimensions)
}

/** The number of pages in a stored /pages/dimensions answer. */
internal fun pageCount(sizesJson: String?): Int? =
    sizesJson?.let { runCatching { KodexJson.decodeFromString(PageDimensions.serializer(), it).dimensions?.size }.getOrNull() }
        ?.takeIf { it > 0 }
