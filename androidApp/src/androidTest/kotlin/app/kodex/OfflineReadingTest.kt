package app.kodex

import android.graphics.Bitmap
import android.graphics.Color
import androidx.compose.ui.test.junit4.createEmptyComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.performTouchInput
import androidx.compose.ui.test.swipeLeft
import androidx.compose.ui.test.hasTestTag
import androidx.test.core.app.ActivityScenario
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.work.ListenableWorker
import androidx.work.testing.TestListenableWorkerBuilder
import androidx.work.workDataOf
import app.kodex.account.AccountStore
import app.kodex.data.db.BookEntity
import app.kodex.data.db.DownloadEntity
import app.kodex.data.db.DownloadKinds
import app.kodex.data.db.DownloadState
import app.kodex.data.db.KodexDatabase
import app.kodex.data.db.LibraryEntity
import app.kodex.download.DownloadWorker
import app.kodex.download.Downloads
import app.kodex.download.Fetcher
import app.kodex.reader.ReaderActivity
import app.kodex.ui.wipe
import java.io.ByteArrayOutputStream
import java.util.zip.ZipEntry
import java.util.zip.ZipOutputStream
import kotlinx.coroutines.runBlocking
import mockwebserver3.Dispatcher
import mockwebserver3.MockResponse
import mockwebserver3.MockWebServer
import mockwebserver3.RecordedRequest
import okio.Buffer
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.koin.core.context.GlobalContext

/**
 * Phase 5's gate on a device: a book is downloaded (resumable, checked against the server's
 * SHA-256), the server goes away, and the book still opens, turns its pages and keeps the
 * reading position, to be sent when the server is back.
 */
@RunWith(AndroidJUnit4::class)
class OfflineReadingTest {
    @get:Rule val compose = createEmptyComposeRule()

    private val context = ApplicationProvider.getApplicationContext<android.content.Context>()
    private val koin get() = GlobalContext.get()
    private val db: KodexDatabase get() = koin.get()
    private val server = MockWebServer()
    private lateinit var cbz: ByteArray

    private fun page(color: Int): ByteArray {
        val bitmap = Bitmap.createBitmap(300, 450, Bitmap.Config.ARGB_8888).apply { eraseColor(color) }
        return ByteArrayOutputStream().also { bitmap.compress(Bitmap.CompressFormat.PNG, 100, it) }.toByteArray()
    }

    @Before
    fun serve() = runBlocking {
        cbz = ByteArrayOutputStream().also { out ->
            ZipOutputStream(out).use { zip ->
                listOf("002.png" to Color.BLUE, "001.png" to Color.RED, "ComicInfo.xml" to 0).forEach { (name, color) ->
                    zip.putNextEntry(ZipEntry(name))
                    zip.write(if (name.endsWith(".png")) page(color) else "<ComicInfo/>".toByteArray())
                    zip.closeEntry()
                }
            }
        }.toByteArray()
        val sha256 = java.security.MessageDigest.getInstance("SHA-256").digest(cbz).joinToString("") { "%02x".format(it) }
        server.dispatcher = object : Dispatcher() {
            override fun dispatch(request: RecordedRequest): MockResponse = when (request.url.encodedPath) {
                "/api/books/1/digest" -> json("""{"sha256":"$sha256","size":${cbz.size}}""")
                "/api/books/1/pages/dimensions" -> json("""{"dimensions":[[300,450],[300,450]],"pending":false}""")
                "/api/books/1/file" -> MockResponse.Builder().code(200).body(Buffer().write(cbz)).build()
                else -> MockResponse.Builder().code(404).body("""{"detail":"Not found"}""").build()
            }
        }
        server.start()
        wipe(db, koin.get<Downloads>())
        koin.get<AccountStore>().save(server.url("/").toString().trimEnd('/'), "kdx_test", "anna")
        db.catalog().upsertLibraries(listOf(LibraryEntity(1, "Serier", "comics")))
        db.catalog().upsertBooks(
            listOf(BookEntity(1, 1, null, "Stjärnhavet #1", "Stjärnhavet #1", 1.0, "cbz", cbz.size.toLong(), 2, "issue", "", null, null, null)),
        )
    }

    /** A page decoded and on screen (the tag is on the image Coil shows once it has loaded). */
    private fun shown(tag: String) = compose.waitUntil(timeoutMillis = 15_000) {
        compose.onAllNodes(hasTestTag(tag), useUnmergedTree = true).fetchSemanticsNodes().isNotEmpty()
    }

    private fun json(body: String) = MockResponse.Builder().code(200).setHeader("Content-Type", "application/json").body(body).build()

    @After
    fun stop() = runBlocking {
        runCatching { server.close() }
        wipe(db, koin.get<Downloads>())
        koin.get<AccountStore>().forget()
    }

    @Test
    fun aDownloadedBookIsReadWithoutTheServer() = runBlocking {
        db.downloads().save(DownloadEntity(1, DownloadState.QUEUED, DownloadKinds.FILE, 0, cbz.size.toLong(), null, null, false, 0, null))
        val worker = TestListenableWorkerBuilder<DownloadWorker>(context).setInputData(workDataOf(DownloadWorker.BOOK_ID to 1)).build()
        assertEquals(ListenableWorker.Result.success(), worker.doWork())
        val download = db.downloads().get(1)!!
        assertEquals(DownloadState.DONE, download.state)
        val file = koin.get<Downloads>().file(1, "cbz")
        assertEquals(download.sha256, Fetcher.sha256(file))

        // The server is gone.
        server.close()

        ActivityScenario.launch<ReaderActivity>(ReaderActivity.intent(context, 1)).use {
            shown("page-shown-0")
            compose.onNodeWithTag("image-reader").performTouchInput { swipeLeft() }
            shown("page-shown-1")
            // The position is kept on the device, waiting for the server.
            compose.waitUntil(timeoutMillis = 10_000) { runBlocking { db.state().pending().isNotEmpty() } }
        }
        val saved = db.catalog().progressNow(1)!!
        assertEquals("1", saved.position)
        assertEquals("page", saved.locatorKind)
        assertTrue(saved.finished)
    }
}
