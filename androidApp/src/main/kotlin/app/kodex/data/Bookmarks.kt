package app.kodex.data

import androidx.room3.withWriteTransaction
import app.kodex.data.db.BookmarkEntity
import app.kodex.data.db.KodexDatabase
import app.kodex.shared.api.BookmarkIn
import app.kodex.shared.api.KodexApi
import app.kodex.shared.api.KodexApiException
import java.time.Instant
import java.util.UUID
import kotlinx.coroutines.flow.Flow

/**
 * Bookmarks on the device, which reach the server when the sync runs: one made here is saved
 * first and sent later (under its own UUID, so sending it twice is fine), one removed here is
 * hidden at once and forgotten when the server has forgotten it too.
 */
class Bookmarks(private val db: KodexDatabase) {
    private val dao = db.bookmarks()

    fun of(bookId: Int): Flow<List<BookmarkEntity>> = dao.of(bookId)

    suspend fun add(bookId: Int, at: Position): BookmarkEntity {
        val bookmark = BookmarkEntity(
            id = UUID.randomUUID().toString(),
            bookId = bookId,
            position = at.position ?: "0",
            locatorKind = at.locatorKind ?: "page",
            percent = at.percent,
            chapter = at.chapter,
            note = null,
            createdAt = Instant.now().toString(),
            pending = BookmarkEntity.Pending.SAVE,
        )
        dao.save(bookmark)
        return bookmark
    }

    suspend fun remove(id: String) {
        val bookmark = dao.get(id) ?: return
        // One the server never got needs nothing from it.
        if (bookmark.pending == BookmarkEntity.Pending.SAVE) dao.delete(id) else dao.markDeleted(id)
    }

    /**
     * Sends what was made or removed here, then takes the server's list ([pull]: on a full sync).
     * A server from before bookmarks (it doesn't know the address) keeps them here until it does.
     */
    suspend fun sync(api: KodexApi, pull: Boolean) {
        try {
            push(api)
            if (pull) pull(api)
        } catch (e: KodexApiException) {
            if (e.unauthorized || e.status !in NOT_THERE) throw e
        }
    }

    private suspend fun push(api: KodexApi) {
        for (bookmark in dao.pending()) {
            when (bookmark.pending) {
                BookmarkEntity.Pending.DELETE -> {
                    api.deleteBookmark(bookmark.id)
                    dao.delete(bookmark.id)
                }
                else -> try {
                    api.saveBookmark(
                        bookmark.id,
                        BookmarkIn(bookmark.bookId, bookmark.position, bookmark.locatorKind, bookmark.percent,
                            bookmark.chapter, bookmark.note, bookmark.createdAt),
                    )
                    dao.sent(bookmark.id)
                } catch (e: KodexApiException) {
                    when {
                        // Its book is gone from the catalog as well: it would never go.
                        e.status == 404 && db.catalog().bookNow(bookmark.bookId) == null -> dao.delete(bookmark.id)
                        // The server can't take it (or another user has its id): neither would it later.
                        e.status == 409 || e.status == 422 -> dao.delete(bookmark.id)
                        else -> throw e
                    }
                }
            }
        }
    }

    private suspend fun pull(api: KodexApi) {
        val remote = api.bookmarks()
        db.withWriteTransaction {
            dao.clearSent()
            remote.forEach {
                if (dao.get(it.id) == null) {
                    dao.save(BookmarkEntity(it.id, it.bookId, it.position, it.locatorKind, it.progressPercent, it.chapter,
                        it.note, it.createdAt, pending = null))
                }
            }
        }
    }

    private companion object {
        /** What a server without bookmarks answers. */
        val NOT_THERE = setOf(404, 405)
    }
}
