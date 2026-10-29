package app.kodex.data.db

import androidx.room3.Dao
import androidx.room3.Query
import androidx.room3.Upsert
import kotlinx.coroutines.flow.Flow

/** A book with what the lists show next to it. */
data class BookRow(
    val id: Int,
    val seriesId: Int?,
    val libraryId: Int,
    val title: String,
    val number: Double?,
    val format: String,
    val fileSize: Long,
    val pageCount: Int?,
    val editionType: String,
    val authors: String,
    val seriesTitle: String?,
    val libraryType: String?,
    val percent: Double?,
    val finished: Boolean?,
    val downloadState: DownloadState?,
    val downloadBytes: Long?,
    val downloadTotal: Long?,
)

data class SeriesRow(
    val id: Int,
    val libraryId: Int,
    val title: String,
    val startYear: Int?,
    val following: Boolean,
    val libraryType: String?,
    val bookCount: Int,
    val readCount: Int,
    /** Books with a position that aren't finished. */
    val startedCount: Int,
    val downloadedCount: Int,
    val firstBookId: Int?,
    /** The newest book's id: the server counts up, so the highest came last. */
    val newestBookId: Int?,
    /** ISO 8601, when any of its books was last read. */
    val lastReadAt: String?,
)

data class ContinueRow(
    val id: Int,
    val title: String,
    val seriesId: Int?,
    val seriesTitle: String?,
    val number: Double?,
    val format: String,
    val pageCount: Int?,
    val libraryType: String?,
    val percent: Double,
    val readAt: String,
    val downloadState: DownloadState?,
)

/** A library and how much is in it. */
data class LibraryRow(val id: Int, val name: String, val libraryType: String, val seriesCount: Int, val bookCount: Int)

data class CatalogCounts(val libraries: Int, val series: Int, val books: Int)

private const val BOOK_ROW = """
    SELECT b.id, b.seriesId, b.libraryId, b.title, b.number, b.format, b.fileSize, b.pageCount, b.editionType, b.authors,
           s.title AS seriesTitle, l.libraryType AS libraryType,
           p.percent AS percent, p.finished AS finished,
           d.state AS downloadState, d.bytes AS downloadBytes, d.total AS downloadTotal
    FROM books b LEFT JOIN series s ON s.id = b.seriesId LEFT JOIN libraries l ON l.id = b.libraryId
    LEFT JOIN progress p ON p.bookId = b.id LEFT JOIN downloads d ON d.bookId = b.id
"""

private const val SERIES_ROW = """
    SELECT s.id, s.libraryId, s.title, s.startYear, s.following, l.libraryType AS libraryType,
           (SELECT count(*) FROM books b WHERE b.seriesId = s.id) AS bookCount,
           (SELECT count(*) FROM books b JOIN progress p ON p.bookId = b.id WHERE b.seriesId = s.id AND p.finished) AS readCount,
           (SELECT count(*) FROM books b JOIN progress p ON p.bookId = b.id
             WHERE b.seriesId = s.id AND NOT p.finished AND p.percent > 0) AS startedCount,
           (SELECT count(*) FROM books b JOIN downloads d ON d.bookId = b.id
             WHERE b.seriesId = s.id AND d.state = 'DONE') AS downloadedCount,
           (SELECT b.id FROM books b WHERE b.seriesId = s.id ORDER BY b.number IS NULL, b.number, b.sortTitle LIMIT 1)
             AS firstBookId,
           (SELECT max(b.id) FROM books b WHERE b.seriesId = s.id) AS newestBookId,
           (SELECT max(p.readAt) FROM books b JOIN progress p ON p.bookId = b.id WHERE b.seriesId = s.id) AS lastReadAt
    FROM series s LEFT JOIN libraries l ON l.id = s.libraryId
"""

private const val CONTINUE_ROW = """
    SELECT b.id, b.title, b.seriesId, s.title AS seriesTitle, b.number, b.format, b.pageCount, l.libraryType AS libraryType,
           p.percent, p.readAt, d.state AS downloadState
    FROM progress p JOIN books b ON b.id = p.bookId LEFT JOIN series s ON s.id = b.seriesId
    LEFT JOIN libraries l ON l.id = b.libraryId LEFT JOIN downloads d ON d.bookId = b.id
    WHERE NOT p.finished AND p.percent > 0 ORDER BY p.readAt DESC
"""

@Dao
interface CatalogDao {
    @Upsert suspend fun upsertLibraries(rows: List<LibraryEntity>)

    @Upsert suspend fun upsertSeries(rows: List<SeriesEntity>)

    @Upsert suspend fun upsertBooks(rows: List<BookEntity>)

    @Upsert suspend fun upsertCollections(rows: List<CollectionEntity>)

    @Upsert suspend fun upsertCollectionBooks(rows: List<CollectionBookEntity>)

    @Upsert suspend fun upsertProgress(rows: List<ProgressEntity>)

    @Query("DELETE FROM libraries WHERE id IN (:ids)") suspend fun deleteLibraries(ids: List<Int>)

    @Query("DELETE FROM series WHERE id IN (:ids)") suspend fun deleteSeries(ids: List<Int>)

    @Query("DELETE FROM books WHERE id IN (:ids)") suspend fun deleteBooks(ids: List<Int>)

    @Query("DELETE FROM collections WHERE id IN (:ids)") suspend fun deleteCollections(ids: List<Int>)

    @Query("DELETE FROM collection_books WHERE collectionId IN (:ids)") suspend fun clearCollectionBooks(ids: List<Int>)

    @Query("DELETE FROM libraries") suspend fun clearLibraries()

    @Query("DELETE FROM series") suspend fun clearSeries()

    @Query("DELETE FROM books") suspend fun clearBooks()

    @Query("DELETE FROM collections") suspend fun clearCollections()

    @Query("DELETE FROM collection_books") suspend fun clearAllCollectionBooks()

    @Query("DELETE FROM progress") suspend fun clearProgress()

    @Query("SELECT * FROM libraries ORDER BY name COLLATE NOCASE")
    fun libraries(): Flow<List<LibraryEntity>>

    @Query("$SERIES_ROW WHERE s.libraryId = :libraryId ORDER BY s.title COLLATE NOCASE")
    fun seriesIn(libraryId: Int): Flow<List<SeriesRow>>

    @Query("SELECT * FROM series WHERE id = :id") fun series(id: Int): Flow<SeriesEntity?>

    @Query("$BOOK_ROW WHERE b.seriesId = :seriesId ORDER BY b.number IS NULL, b.number, b.sortTitle COLLATE NOCASE")
    fun booksIn(seriesId: Int): Flow<List<BookRow>>

    @Query("$BOOK_ROW WHERE b.libraryId = :libraryId AND b.seriesId IS NULL ORDER BY b.sortTitle COLLATE NOCASE")
    fun looseBooks(libraryId: Int): Flow<List<BookRow>>

    @Query("SELECT * FROM books WHERE id = :id") fun book(id: Int): Flow<BookEntity?>

    @Query("SELECT * FROM books WHERE id = :id") suspend fun bookNow(id: Int): BookEntity?

    @Query("SELECT * FROM progress WHERE bookId = :bookId") fun progress(bookId: Int): Flow<ProgressEntity?>

    @Query("SELECT * FROM progress WHERE bookId = :bookId") suspend fun progressNow(bookId: Int): ProgressEntity?

    @Query("$CONTINUE_ROW LIMIT :limit")
    fun continueReading(limit: Int = 20): Flow<List<ContinueRow>>

    @Query("$CONTINUE_ROW LIMIT 1")
    suspend fun lastRead(): ContinueRow?

    @Query("SELECT * FROM collections ORDER BY name COLLATE NOCASE") fun collections(): Flow<List<CollectionEntity>>

    @Query("$BOOK_ROW JOIN collection_books c ON c.bookId = b.id WHERE c.collectionId = :collectionId ORDER BY c.position")
    fun collectionBooks(collectionId: Int): Flow<List<BookRow>>

    @Query("SELECT * FROM collections WHERE id = :id") fun collection(id: Int): Flow<CollectionEntity?>

    @Query("$BOOK_ROW WHERE b.title LIKE '%' || :text || '%' ORDER BY b.sortTitle COLLATE NOCASE LIMIT 100")
    fun searchBooks(text: String): Flow<List<BookRow>>

    @Query("$SERIES_ROW WHERE s.title LIKE '%' || :text || '%' ORDER BY s.title COLLATE NOCASE LIMIT 50")
    fun searchSeries(text: String): Flow<List<SeriesRow>>

    @Query("$SERIES_ROW WHERE s.following ORDER BY s.title COLLATE NOCASE")
    fun followedSeries(): Flow<List<SeriesRow>>

    @Query("$SERIES_ROW WHERE s.id = :id") fun seriesRow(id: Int): Flow<SeriesRow?>

    /** The newest books (the server's ids count up). */
    @Query("$BOOK_ROW ORDER BY b.id DESC LIMIT :limit")
    fun recentlyAdded(limit: Int = 30): Flow<List<BookRow>>

    @Query("$BOOK_ROW WHERE d.state = 'DONE' ORDER BY d.finishedAt DESC")
    fun downloadedBooks(): Flow<List<BookRow>>

    @Query("$BOOK_ROW WHERE b.id = :id") fun bookRow(id: Int): Flow<BookRow?>

    @Query(
        """SELECT l.id, l.name, l.libraryType,
                  (SELECT count(*) FROM series s WHERE s.libraryId = l.id) AS seriesCount,
                  (SELECT count(*) FROM books b WHERE b.libraryId = l.id) AS bookCount
           FROM libraries l ORDER BY l.name COLLATE NOCASE""",
    )
    fun libraryRows(): Flow<List<LibraryRow>>

    @Query(
        """SELECT (SELECT count(*) FROM libraries) AS libraries, (SELECT count(*) FROM series) AS series,
                  (SELECT count(*) FROM books) AS books""",
    )
    fun counts(): Flow<CatalogCounts>

    @Query("SELECT l.libraryType FROM books b JOIN libraries l ON l.id = b.libraryId WHERE b.id = :bookId")
    suspend fun libraryTypeOf(bookId: Int): String?

    @Query("UPDATE series SET following = :following WHERE id = :id") suspend fun setFollowing(id: Int, following: Boolean)

    /**
     * The books after [bookId] in its series that aren't finished and aren't downloaded, in
     * reading order: what "download the next ones" fetches.
     */
    @Query(
        """SELECT b.* FROM books b JOIN books cur ON cur.id = :bookId
           LEFT JOIN progress p ON p.bookId = b.id LEFT JOIN downloads d ON d.bookId = b.id
           WHERE b.seriesId = cur.seriesId AND b.id != cur.id
             AND (b.number > cur.number OR (b.number = cur.number AND b.sortTitle > cur.sortTitle)
                  OR (cur.number IS NULL AND b.sortTitle > cur.sortTitle))
             AND (p.finished IS NULL OR NOT p.finished) AND d.bookId IS NULL
           ORDER BY b.number IS NULL, b.number, b.sortTitle LIMIT :count""",
    )
    suspend fun nextToFetch(bookId: Int, count: Int): List<BookEntity>

    /** The book after [bookId] in its series, read or not: "next" at the end of a book. */
    @Query(
        """SELECT b.* FROM books b JOIN books cur ON cur.id = :bookId
           WHERE b.seriesId = cur.seriesId AND b.id != cur.id
             AND (b.number > cur.number OR (b.number = cur.number AND b.sortTitle > cur.sortTitle)
                  OR (cur.number IS NULL AND b.sortTitle > cur.sortTitle))
           ORDER BY b.number IS NULL, b.number, b.sortTitle LIMIT 1""",
    )
    suspend fun nextInSeries(bookId: Int): BookEntity?

    /** Books being read here (a position, not finished) that are downloaded: where "next" starts. */
    @Query(
        """SELECT p.bookId FROM progress p JOIN downloads d ON d.bookId = p.bookId
           WHERE NOT p.finished AND d.state = 'DONE' ORDER BY p.readAt DESC LIMIT 10""",
    )
    suspend fun readingDownloaded(): List<Int>
}
