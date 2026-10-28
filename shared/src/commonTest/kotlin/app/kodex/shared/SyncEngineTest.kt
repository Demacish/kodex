package app.kodex.shared

import app.kodex.shared.api.SyncChanges
import app.kodex.shared.sync.CatalogStore
import app.kodex.shared.sync.Cursors
import app.kodex.shared.sync.SyncEngine
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertTrue
import kotlinx.coroutines.test.runTest

private class MemoryStore : CatalogStore {
    var cursors = Cursors()
    val books = mutableMapOf<Int, String>()
    var resets = 0

    override suspend fun cursors() = cursors

    override suspend fun apply(changes: SyncChanges) {
        changes.books.forEach { books[it.id] = it.title }
        changes.deleted.books.forEach { books.remove(it) }
        cursors = Cursors(changes.cursor, changes.progressCursor)
    }

    override suspend fun reset() {
        resets += 1
        books.clear()
        cursors = Cursors()
    }
}

private fun book(id: Int, title: String) =
    """{"id":$id,"library_id":1,"file_path":"s/$id.cbz","file_format":"cbz","file_size":1,"edition_type":"issue",
    "book_metadata":{"title":"$title","sort_title":"$title"}}"""

class SyncEngineTest {
    @Test
    fun pagesUntilTheServerHasNoMore() = runTest {
        val server = FakeServer { request ->
            when (request.url.parameters["since"]) {
                "0" -> json("""{"cursor":2,"more":true,"books":[${book(1, "Ett")},${book(2, "Två")}],"progress_cursor":0}""")
                "2" -> json("""{"cursor":3,"more":false,"books":[${book(3, "Tre")}],"progress_cursor":0}""")
                else -> error("asked from ${request.url}")
            }
        }
        val store = MemoryStore()
        val result = SyncEngine(server.api(), store).sync()
        assertEquals(2, result.pages)
        assertEquals(mapOf(1 to "Ett", 2 to "Två", 3 to "Tre"), store.books)
        assertEquals(Cursors(3, 0), store.cursors)
    }

    @Test
    fun deletionsRemoveAndTheCursorsAreKept() = runTest {
        val server = FakeServer { json("""{"cursor":9,"more":false,"deleted":{"books":[2]},"progress_cursor":4}""") }
        val store = MemoryStore().apply { books += mapOf(1 to "Ett", 2 to "Två"); cursors = Cursors(5, 1) }
        SyncEngine(server.api(), store).sync()
        assertEquals(mapOf(1 to "Ett"), store.books)
        assertEquals("5", server.requests.single().url.parameters["since"])
        assertEquals(Cursors(9, 4), store.cursors)
    }

    @Test
    fun aResetStartsOverOnce() = runTest {
        val server = FakeServer { request ->
            if (request.url.parameters["since"] == "50") {
                json("""{"cursor":0,"more":true,"reset":true,"progress_cursor":0}""")
            } else {
                json("""{"cursor":1,"more":false,"books":[${book(7, "Sju")}],"progress_cursor":0}""")
            }
        }
        val store = MemoryStore().apply { books += 1 to "Gammal"; cursors = Cursors(50, 3) }
        val result = SyncEngine(server.api(), store).sync()
        assertTrue(result.reset)
        assertEquals(1, store.resets)
        assertEquals(mapOf(7 to "Sju"), store.books)
    }

    @Test
    fun aServerThatKeepsResettingIsAnError() = runTest {
        val server = FakeServer { json("""{"cursor":0,"more":true,"reset":true,"progress_cursor":0}""") }
        assertFailsWith<IllegalStateException> { SyncEngine(server.api(), MemoryStore()).sync() }
    }

    @Test
    fun positionsPageOnTheirOwnCursor() = runTest {
        val server = FakeServer { request ->
            when (request.url.parameters["progress_since"]) {
                "0" -> json("""{"cursor":1,"more":false,"progress_cursor":5,"progress_more":true,
                    "progress":[{"book_id":1,"position":"2","progress_percent":10.0,"is_finished":false,"last_read_at":"2026-10-26T10:00:00Z"}]}""")
                else -> json("""{"cursor":1,"more":false,"progress_cursor":6}""")
            }
        }
        val store = MemoryStore()
        SyncEngine(server.api(), store).sync()
        assertEquals(Cursors(1, 6), store.cursors)
        assertEquals(2, server.requests.size)
    }
}
