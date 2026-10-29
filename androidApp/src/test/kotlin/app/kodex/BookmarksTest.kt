package app.kodex

import android.app.Application
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import app.kodex.data.Bookmarks
import app.kodex.data.Position
import app.kodex.data.db.BookEntity
import app.kodex.data.db.BookmarkEntity
import app.kodex.data.db.KodexDatabase
import app.kodex.shared.api.KodexApi
import io.ktor.client.engine.mock.MockEngine
import io.ktor.client.engine.mock.respond
import io.ktor.http.HttpMethod
import io.ktor.http.HttpStatusCode
import io.ktor.http.headersOf
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.test.runTest
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.annotation.Config

/** Bookmarks on the device (data/Bookmarks.kt): sent when the sync runs, and the server's taken in. */
@RunWith(AndroidJUnit4::class)
@Config(application = Application::class)
class BookmarksTest {
    private lateinit var db: KodexDatabase
    private lateinit var bookmarks: Bookmarks
    private val calls = mutableListOf<String>()

    @Before
    fun open() {
        db = KodexDatabase.inMemory(ApplicationProvider.getApplicationContext())
        bookmarks = Bookmarks(db)
    }

    @After
    fun close() = db.close()

    private fun api(remote: String = "[]", known: Boolean = true) = KodexApi(
        "https://kodex.test",
        { "kdx_test" },
        MockEngine { request ->
            calls += "${request.method.value} ${request.url.encodedPath}"
            val json = headersOf("Content-Type", "application/json")
            when {
                !known -> respond("""{"detail":"Not Found"}""", HttpStatusCode.NotFound, json)
                request.method == HttpMethod.Get -> respond(remote, HttpStatusCode.OK, json)
                request.method == HttpMethod.Delete -> respond("", HttpStatusCode.NoContent)
                else -> respond(
                    """{"id":"${request.url.encodedPath.substringAfterLast('/')}","book_id":1,"position":"4","locator_kind":"page",
                    "progress_percent":20,"created_at":"2026-10-29T20:00:00Z"}""",
                    HttpStatusCode.OK, json,
                )
            }
        },
    )

    @Test
    fun oneMadeHereIsSentThenKept() = runTest {
        val made = bookmarks.add(1, Position("4", "page", 20.0, false))
        bookmarks.sync(api(), pull = false)
        assertEquals(listOf("PUT /api/bookmarks/${made.id}"), calls)
        assertNull(db.bookmarks().get(made.id)!!.pending)
    }

    @Test
    fun oneRemovedBeforeItWasSentNeverGoes() = runTest {
        val made = bookmarks.add(1, Position("4", "page", 20.0, false))
        bookmarks.remove(made.id)
        bookmarks.sync(api(), pull = false)
        assertTrue(calls.isEmpty())
        assertTrue(bookmarks.of(1).first().isEmpty())
    }

    @Test
    fun oneRemovedAfterwardsIsDeletedOnTheServer() = runTest {
        db.bookmarks().save(BookmarkEntity("b1", 1, "2", "page", 10.0, null, null, "2026-10-29T20:00:00Z", pending = null))
        bookmarks.remove("b1")
        assertTrue(bookmarks.of(1).first().isEmpty())
        bookmarks.sync(api(), pull = false)
        assertEquals(listOf("DELETE /api/bookmarks/b1"), calls)
        assertNull(db.bookmarks().get("b1"))
    }

    @Test
    fun theServersListReplacesWhatItHadSent() = runTest {
        db.bookmarks().save(BookmarkEntity("old", 1, "2", "page", 10.0, null, null, "2026-10-29T20:00:00Z", pending = null))
        val remote = """[{"id":"new","book_id":1,"position":"9","locator_kind":"page","progress_percent":45,
            "chapter":null,"note":null,"created_at":"2026-10-29T21:00:00Z"}]"""
        bookmarks.sync(api(remote), pull = true)
        assertEquals(listOf("new"), bookmarks.of(1).first().map { it.id })
    }

    @Test
    fun aServerWithoutBookmarksKeepsThemHere() = runTest {
        db.catalog().upsertBooks(listOf(BookEntity(1, 1, null, "Stjärnhavet #1", "Stjärnhavet #1", 1.0, "cbz", 10, 20, "issue", "", null, null, null)))
        val made = bookmarks.add(1, Position("4", "page", 20.0, false))
        bookmarks.sync(api(known = false), pull = true)
        assertEquals(BookmarkEntity.Pending.SAVE, db.bookmarks().get(made.id)!!.pending)
    }
}
