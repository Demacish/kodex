package app.kodex

import android.app.Application
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import app.kodex.data.Position
import app.kodex.data.Positions
import app.kodex.data.RoomCatalogStore
import app.kodex.data.db.KodexDatabase
import app.kodex.shared.api.KodexJson
import app.kodex.shared.api.SyncChanges
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

private fun book(id: Int, series: Int, title: String) =
    """{"id":$id,"library_id":1,"series_id":$series,"file_path":"s/$id.cbz","file_format":"cbz","file_size":10,
    "page_count":20,"number":$id.0,"edition_type":"issue","book_metadata":{"title":"$title","sort_title":"$title"}}"""

private fun changes(json: String): SyncChanges = KodexJson.decodeFromString(SyncChanges.serializer(), json)

/** The catalog in Room as the sync fills it (data/Catalog.kt) and the positions read here. */
@RunWith(AndroidJUnit4::class)
@Config(application = Application::class)
class CatalogStoreTest {
    private lateinit var db: KodexDatabase
    private lateinit var store: RoomCatalogStore
    private lateinit var positions: Positions

    @Before
    fun open() {
        db = KodexDatabase.inMemory(ApplicationProvider.getApplicationContext())
        store = RoomCatalogStore(db, "anna@https://kodex.test")
        positions = Positions(db) { "Pixel" }
    }

    @After
    fun close() = db.close()

    private val first = changes(
        """{"cursor":5,"more":false,"progress_cursor":2,
        "libraries":[{"id":1,"name":"Serier","path":"serier","library_type":"comics"}],
        "series":[{"id":7,"library_id":1,"title":"Stjärnhavet","path":"s","book_count":2}],
        "books":[${book(1, 7, "Stjärnhavet #1")},${book(2, 7, "Stjärnhavet #2")}],
        "collections":[{"id":3,"name":"Läslista","collection_type":"manual","book_ids":[2,1]}],
        "progress":[{"book_id":1,"position":"4","locator_kind":"page","progress_percent":25.0,"is_finished":false,
          "last_read_at":"2026-10-26T10:00:00Z","device_name":"Läsplatta"}]}""",
    )

    @Test
    fun aPageGoesInWithItsCursors() = runTest {
        store.apply(first)
        assertEquals(5L, store.cursors().catalog)
        assertEquals(2L, store.cursors().progress)
        assertEquals(listOf("Stjärnhavet #1", "Stjärnhavet #2"), db.catalog().booksIn(7).first().map { it.title })
        assertEquals(listOf(2, 1), db.catalog().collectionBooks(3).first().map { it.id })
        assertEquals("4", db.catalog().progressNow(1)?.position)
        assertEquals(1, db.catalog().seriesIn(1).first().single().firstBookId)
    }

    @Test
    fun deletionsGo() = runTest {
        store.apply(first)
        store.apply(changes("""{"cursor":6,"more":false,"progress_cursor":2,"deleted":{"books":[2],"collections":[3]}}"""))
        assertEquals(listOf(1), db.catalog().booksIn(7).first().map { it.id })
        assertTrue(db.catalog().collections().first().isEmpty())
    }

    @Test
    fun aPositionReadHereWinsUntilItIsSent() = runTest {
        store.apply(first)
        positions.record(1, Position("9", "page", 50.0, false))
        store.apply(
            changes(
                """{"cursor":6,"more":false,"progress_cursor":3,"progress":[{"book_id":1,"position":"5","locator_kind":"page",
                "progress_percent":30.0,"is_finished":false,"last_read_at":"2026-10-26T11:00:00Z"}]}""",
            ),
        )
        assertEquals("9", db.catalog().progressNow(1)?.position)
        val pending = positions.pending().single()
        assertEquals(1L, pending.seq)
        positions.sent(pending.id)
        store.apply(
            changes(
                """{"cursor":7,"more":false,"progress_cursor":4,"progress":[{"book_id":1,"position":"9","locator_kind":"page",
                "progress_percent":50.0,"is_finished":false,"last_read_at":"2026-10-26T11:01:00Z","device_name":"Pixel"}]}""",
            ),
        )
        assertEquals("9", db.catalog().progressNow(1)?.position)
    }

    @Test
    fun reportNumbersKeepGrowing() = runTest {
        positions.record(1, Position("1", "page", 5.0, false))
        store.apply(first)
        positions.record(1, Position("2", "page", 10.0, false))
        assertEquals(listOf(1L, 2L), positions.pending().map { it.seq })
    }

    @Test
    fun aResetForgetsTheCatalogButNotWhatWasRead() = runTest {
        store.apply(first)
        positions.record(2, Position("3", "page", 15.0, false))
        store.reset()
        assertEquals(0L, store.cursors().catalog)
        assertTrue(db.catalog().booksIn(7).first().isEmpty())
        assertEquals(1, positions.pending().size)
    }

    @Test
    fun anotherAccountStartsFromNothing() = runTest {
        store.apply(first)
        positions.record(1, Position("9", "page", 50.0, false))
        val other = RoomCatalogStore(db, "bo@https://kodex.test")
        assertEquals(0L, other.cursors().catalog)
        other.apply(changes("""{"cursor":1,"more":false,"progress_cursor":0}"""))
        assertTrue(db.catalog().booksIn(7).first().isEmpty())
        assertNull(db.catalog().progressNow(1))
        assertTrue(positions.pending().isEmpty())
    }

    @Test
    fun theNextOnesInASeriesAreTheUnreadOnesAfter() = runTest {
        store.apply(
            changes(
                """{"cursor":3,"more":false,"progress_cursor":0,"books":[${book(1, 7, "a")},${book(2, 7, "b")},${book(3, 7, "c")},
                ${book(4, 7, "d")}],"progress":[{"book_id":3,"progress_percent":100.0,"is_finished":true,"last_read_at":"2026-10-26T10:00:00Z"}]}""",
            ),
        )
        assertEquals(listOf(2, 4), db.catalog().nextToFetch(1, 5).map { it.id })
        assertEquals(listOf(2), db.catalog().nextToFetch(1, 1).map { it.id })
    }
}
