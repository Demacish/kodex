package app.kodex.data.db

import androidx.room3.Dao
import androidx.room3.Query
import androidx.room3.Upsert
import kotlinx.coroutines.flow.Flow

/** A book with what the lists show next to it. */
data class BookRow(
    val id: Int,
    val seriesId: Int?,
    val title: String,
    val number: Double?,
    val format: String,
    val fileSize: Long,
    val pageCount: Int?,
    val percent: Double?,
    val finished: Boolean?,
    val downloadState: DownloadState?,
)

data class SeriesRow(
    val id: Int,
    val libraryId: Int,
    val title: String,
    val startYear: Int?,
    val bookCount: Int,
    val readCount: Int,
    val firstBookId: Int?,
)

data class ContinueRow(
    val id: Int,
    val title: String,
    val seriesTitle: String?,
    val format: String,
    val percent: Double,
    val readAt: String,
    val downloadState: DownloadState?,
)

private const val BOOK_ROW = """
    SELECT b.id, b.seriesId, b.title, b.number, b.format, b.fileSize, b.pageCount,
           p.percent AS percent, p.finished AS finished, d.state AS downloadState
    FROM books b LEFT JOIN progress p ON p.bookId = b.id LEFT JOIN downloads d ON d.bookId = b.id
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

    @Query(
        """SELECT s.id, s.libraryId, s.title, s.startYear,
                  (SELECT count(*) FROM books b WHERE b.seriesId = s.id) AS bookCount,
                  (SELECT count(*) FROM books b JOIN progress p ON p.bookId = b.id
                    WHERE b.seriesId = s.id AND p.finished) AS readCount,
                  (SELECT b.id FROM books b WHERE b.seriesId = s.id ORDER BY b.number IS NULL, b.number, b.sortTitle LIMIT 1)
                    AS firstBookId
           FROM series s WHERE s.libraryId = :libraryId ORDER BY s.title COLLATE NOCASE""",
    )
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

    @Query(
        """SELECT b.id, b.title, s.title AS seriesTitle, b.format, p.percent, p.readAt, d.state AS downloadState
           FROM progress p JOIN books b ON b.id = p.bookId LEFT JOIN series s ON s.id = b.seriesId
           LEFT JOIN downloads d ON d.bookId = b.id
           WHERE NOT p.finished AND p.percent > 0 ORDER BY p.readAt DESC LIMIT :limit""",
    )
    fun continueReading(limit: Int = 20): Flow<List<ContinueRow>>

    @Query(
        """SELECT b.id, b.title, s.title AS seriesTitle, b.format, p.percent, p.readAt, d.state AS downloadState
           FROM progress p JOIN books b ON b.id = p.bookId LEFT JOIN series s ON s.id = b.seriesId
           LEFT JOIN downloads d ON d.bookId = b.id
           WHERE NOT p.finished AND p.percent > 0 ORDER BY p.readAt DESC LIMIT 1""",
    )
    suspend fun lastRead(): ContinueRow?

    @Query("SELECT * FROM collections ORDER BY name COLLATE NOCASE") fun collections(): Flow<List<CollectionEntity>>

    @Query(
        """SELECT b.id, b.seriesId, b.title, b.number, b.format, b.fileSize, b.pageCount,
                  p.percent AS percent, p.finished AS finished, d.state AS downloadState
           FROM collection_books c JOIN books b ON b.id = c.bookId
           LEFT JOIN progress p ON p.bookId = b.id LEFT JOIN downloads d ON d.bookId = b.id
           WHERE c.collectionId = :collectionId ORDER BY c.position""",
    )
    fun collectionBooks(collectionId: Int): Flow<List<BookRow>>

    @Query("SELECT * FROM collections WHERE id = :id") fun collection(id: Int): Flow<CollectionEntity?>

    @Query("$BOOK_ROW WHERE b.title LIKE '%' || :text || '%' ORDER BY b.sortTitle COLLATE NOCASE LIMIT 100")
    fun searchBooks(text: String): Flow<List<BookRow>>

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
