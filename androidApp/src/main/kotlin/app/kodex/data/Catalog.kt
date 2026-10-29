package app.kodex.data

import app.kodex.data.db.BookEntity
import app.kodex.data.db.CATALOG_VERSION
import app.kodex.data.db.CollectionBookEntity
import app.kodex.data.db.CollectionEntity
import app.kodex.data.db.KodexDatabase
import app.kodex.data.db.LibraryEntity
import app.kodex.data.db.ProgressEntity
import app.kodex.data.db.SeriesEntity
import app.kodex.data.db.SyncStateEntity
import app.kodex.shared.api.Book
import app.kodex.shared.api.SyncChanges
import app.kodex.shared.sync.CatalogStore
import app.kodex.shared.sync.Cursors
import androidx.room3.withWriteTransaction

/**
 * The catalog in Room, as the shared SyncEngine fills it. Each page goes in with its cursors in
 * one transaction. Downloads aren't touched here: a book the server no longer has keeps its
 * file until [app.kodex.download.Downloads.prune] removes it.
 */
class RoomCatalogStore(private val db: KodexDatabase, private val owner: String) : CatalogStore {
    private val catalog = db.catalog()
    private val state = db.state()

    override suspend fun cursors(): Cursors {
        val saved = state.state() ?: return Cursors()
        if (saved.owner != owner) return Cursors()
        // A catalog kept by an older app lacks fields this one shows: it comes again from the start.
        return Cursors(if (saved.catalogVersion < CATALOG_VERSION) 0 else saved.catalogCursor, saved.progressCursor)
    }

    /** Positions read before the first sync have no account yet; that isn't another account. */
    private fun SyncStateEntity.otherAccount(): Boolean = owner.isNotEmpty() && owner != this@RoomCatalogStore.owner

    private fun SyncStateEntity?.seq(): Long = this?.takeUnless { it.otherAccount() }?.lastSeq ?: 0

    override suspend fun apply(changes: SyncChanges) {
        db.withWriteTransaction {
            val saved = state.state()
            if (saved != null && saved.otherAccount()) clearCatalog(positions = true)
            catalog.upsertLibraries(changes.libraries.map { LibraryEntity(it.id, it.name, it.libraryType) })
            catalog.upsertSeries(
                changes.series.map {
                    SeriesEntity(it.id, it.libraryId, it.title, it.startYear, it.publisher, it.summary, it.bookCount, it.isFollowing,
                        it.status)
                },
            )
            catalog.upsertBooks(changes.books.map { it.toEntity() })
            if (changes.collections.isNotEmpty()) {
                val ids = changes.collections.map { it.id }
                catalog.clearCollectionBooks(ids)
                catalog.upsertCollections(changes.collections.map { CollectionEntity(it.id, it.name, it.collectionType) })
                catalog.upsertCollectionBooks(
                    changes.collections.flatMap { c -> c.bookIds.mapIndexed { i, book -> CollectionBookEntity(c.id, i, book) } },
                )
            }
            with(changes.deleted) {
                if (books.isNotEmpty()) catalog.deleteBooks(books)
                if (series.isNotEmpty()) catalog.deleteSeries(series)
                if (libraries.isNotEmpty()) catalog.deleteLibraries(libraries)
                if (collections.isNotEmpty()) {
                    catalog.clearCollectionBooks(collections)
                    catalog.deleteCollections(collections)
                }
            }
            // A position read here and not yet sent stays: it is the newest once it arrives.
            val fromServer = changes.progress.filterNot { state.hasPending(it.bookId) }
            catalog.upsertProgress(
                fromServer.map {
                    ProgressEntity(it.bookId, it.position, it.locatorKind, it.progressPercent, it.isFinished, it.chapter,
                        it.lastReadAt, it.deviceName)
                },
            )
            state.save(
                SyncStateEntity(
                    catalogCursor = changes.cursor,
                    progressCursor = changes.progressCursor,
                    owner = owner,
                    syncedAt = System.currentTimeMillis(),
                    lastSeq = saved.seq(),
                    catalogVersion = CATALOG_VERSION,
                ),
            )
        }
    }

    override suspend fun reset() {
        db.withWriteTransaction {
            val saved = state.state()
            clearCatalog(positions = false)
            state.save(SyncStateEntity(0, 0, 0, owner, null, saved.seq()))
        }
    }

    /**
     * A reset keeps the positions: the server sends its own again, and one read here and not yet
     * sent still goes (the server drops it if the book is gone). Another account's go.
     */
    private suspend fun clearCatalog(positions: Boolean) {
        catalog.clearAllCollectionBooks()
        catalog.clearCollections()
        catalog.clearBooks()
        catalog.clearSeries()
        catalog.clearLibraries()
        if (positions) {
            catalog.clearProgress()
            state.clearOutbox()
        }
    }
}

fun Book.toEntity() = BookEntity(
    id = id,
    libraryId = libraryId,
    seriesId = seriesId,
    title = title,
    sortTitle = bookMetadata?.sortTitle ?: title,
    number = number,
    format = fileFormat,
    fileSize = fileSize,
    pageCount = pageCount,
    editionType = editionType,
    authors = bookMetadata?.authors.orEmpty().joinToString(", "),
    summary = bookMetadata?.summary,
    publishedYear = bookMetadata?.publishedYear,
    language = bookMetadata?.language,
    filePath = filePath,
    genres = bookMetadata?.genres.orEmpty().joinToString(", "),
)
