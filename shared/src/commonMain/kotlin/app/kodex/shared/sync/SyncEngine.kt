package app.kodex.shared.sync

import app.kodex.shared.api.KodexApi
import app.kodex.shared.api.SyncChanges

/** Where the app keeps the catalog: the two cursors and what the server sends. */
interface CatalogStore {
    suspend fun cursors(): Cursors

    /**
     * Saves one page of changes and its cursors together (one transaction), so a sync that
     * stops halfway goes on from the last saved page. A position from the server doesn't
     * replace one read on this device that is still in the outbox: that one becomes the
     * newest when it arrives.
     */
    suspend fun apply(changes: SyncChanges)

    /** The server's history isn't the one the cursors came from: forget the catalog. */
    suspend fun reset()
}

data class Cursors(val catalog: Long = 0, val progress: Long = 0)

data class SyncResult(val pages: Int, val changed: Int, val reset: Boolean)

/** Brings the store up to date with the server, a page at a time (GET /api/sync/changes). */
class SyncEngine(private val api: KodexApi, private val store: CatalogStore, private val pageSize: Int = 500) {
    suspend fun sync(): SyncResult {
        var pages = 0
        var changed = 0
        var reset = false
        while (true) {
            val at = store.cursors()
            val page = api.changes(at.catalog, at.progress, pageSize)
            pages += 1
            if (page.reset) {
                // Only once: a server that keeps answering reset has something wrong with it.
                check(!reset) { "The server reset the sync twice" }
                reset = true
                store.reset()
                continue
            }
            store.apply(page)
            changed += page.size
            if (!page.more && !page.progressMore) return SyncResult(pages, changed, reset)
            check(page.cursor > at.catalog || page.progressCursor > at.progress) {
                "The sync didn't move on"
            }
        }
    }
}

val SyncChanges.size: Int
    get() = libraries.size + series.size + books.size + collections.size + progress.size +
        deleted.libraries.size + deleted.series.size + deleted.books.size + deleted.collections.size
