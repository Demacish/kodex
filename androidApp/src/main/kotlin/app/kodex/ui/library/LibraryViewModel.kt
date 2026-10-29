package app.kodex.ui.library

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import app.kodex.R
import app.kodex.account.AccountStore
import app.kodex.data.Bookmarks
import app.kodex.data.Position
import app.kodex.data.Positions
import app.kodex.data.db.BookRow
import app.kodex.data.db.DownloadState
import app.kodex.data.db.KodexDatabase
import app.kodex.data.db.SeriesRow
import app.kodex.download.Downloads
import app.kodex.sync.ApiProvider
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.flatMapLatest
import kotlinx.coroutines.flow.flowOf
import kotlinx.coroutines.launch

/** How a library's series are ordered. */
enum class SeriesSort { TITLE, ADDED, READ }

/** Which of a library's series (or books) are shown. */
enum class SeriesFilter { ALL, STARTED, UNREAD, FINISHED, FOLLOWING, DOWNLOADED }

fun List<SeriesRow>.shown(show: SeriesFilter, order: SeriesSort): List<SeriesRow> {
    val kept = filter { s ->
        when (show) {
            SeriesFilter.ALL -> true
            SeriesFilter.STARTED -> s.startedCount > 0 || s.readCount in 1 until s.bookCount
            SeriesFilter.UNREAD -> s.readCount == 0 && s.startedCount == 0
            SeriesFilter.FINISHED -> s.bookCount > 0 && s.readCount == s.bookCount
            SeriesFilter.FOLLOWING -> s.following
            SeriesFilter.DOWNLOADED -> s.downloadedCount > 0
        }
    }
    return when (order) {
        SeriesSort.TITLE -> kept
        SeriesSort.ADDED -> kept.sortedByDescending { it.newestBookId ?: 0 }
        SeriesSort.READ -> kept.sortedByDescending { it.lastReadAt.orEmpty() }
    }
}

fun List<BookRow>.shownBooks(show: SeriesFilter, order: SeriesSort): List<BookRow> {
    val kept = filter { b ->
        when (show) {
            SeriesFilter.ALL -> true
            // Books outside a series aren't followed.
            SeriesFilter.FOLLOWING -> false
            SeriesFilter.STARTED -> b.finished != true && (b.percent ?: 0.0) > 0
            SeriesFilter.UNREAD -> b.finished != true && (b.percent ?: 0.0) <= 0
            SeriesFilter.FINISHED -> b.finished == true
            SeriesFilter.DOWNLOADED -> b.downloadState == DownloadState.DONE
        }
    }
    return if (order == SeriesSort.ADDED) kept.sortedByDescending { it.id } else kept
}

/** The catalog on the device, for the lists (all of it works offline). */
class LibraryViewModel(db: KodexDatabase) : ViewModel() {
    private val catalog = db.catalog()

    val libraries = catalog.libraryRows()
    val continueReading = catalog.continueReading()
    val recentlyAdded = catalog.recentlyAdded()
    val collections = catalog.collections()
    val downloaded = catalog.downloadedBooks()

    fun series(libraryId: Int) = catalog.seriesIn(libraryId)

    fun looseBooks(libraryId: Int) = catalog.looseBooks(libraryId)

    fun collectionBooks(id: Int) = catalog.collectionBooks(id)

    val query = MutableStateFlow("")

    @OptIn(ExperimentalCoroutinesApi::class)
    val results: Flow<List<BookRow>> = query.flatMapLatest { text ->
        if (text.isBlank()) flowOf(emptyList()) else catalog.searchBooks(text.trim())
    }

    @OptIn(ExperimentalCoroutinesApi::class)
    val seriesResults: Flow<List<SeriesRow>> = query.flatMapLatest { text ->
        if (text.isBlank()) flowOf(emptyList()) else catalog.searchSeries(text.trim())
    }
}

/** Marking read, downloading and removing books, one or many at a time. */
abstract class BooksActions(
    protected val db: KodexDatabase,
    protected val downloads: Downloads,
    protected val positions: Positions,
) : ViewModel() {
    fun markRead(ids: Collection<Int>, finished: Boolean) = viewModelScope.launch {
        ids.forEach { positions.record(it, if (finished) Position(null, null, 100.0, true) else Position(null, null, 0.0, false)) }
    }

    fun download(ids: Collection<Int>) = viewModelScope.launch {
        ids.forEach { id -> db.catalog().bookNow(id)?.let { downloads.request(it) } }
    }

    fun removeDownloads(ids: Collection<Int>) = viewModelScope.launch { ids.forEach { downloads.remove(it) } }

    fun pause(id: Int) = viewModelScope.launch { downloads.pause(id) }

    fun resume(id: Int) = viewModelScope.launch { downloads.resume(id) }
}

/** A series: its books, following it on the server, and its books all at once. */
class SeriesViewModel(
    val seriesId: Int,
    db: KodexDatabase,
    downloads: Downloads,
    positions: Positions,
    private val accounts: AccountStore,
    private val apis: ApiProvider,
) : BooksActions(db, downloads, positions) {
    val series = db.catalog().series(seriesId)
    val row = db.catalog().seriesRow(seriesId)
    val books = db.catalog().booksIn(seriesId)

    /** Following or not is on its way to the server. */
    val following = MutableStateFlow(false)

    /** Why the last thing asked of the server didn't happen (a string resource). */
    val problem = MutableStateFlow<Int?>(null)

    fun follow(on: Boolean) = viewModelScope.launch {
        val session = accounts.current() ?: return@launch
        following.value = true
        try {
            apis.api(session).follow(seriesId, on)
            db.catalog().setFollowing(seriesId, on)
            problem.value = null
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            problem.value = R.string.follow_failed
        } finally {
            following.value = false
        }
    }

    /** Every book of the series that isn't on the device yet, in reading order. */
    fun downloadAll() = viewModelScope.launch {
        val missing = books.first().filter { it.downloadState == null || it.downloadState == DownloadState.FAILED }
        downloads.requestAll(missing.mapNotNull { db.catalog().bookNow(it.id) })
    }
}

/** One book: its details, position, download and bookmarks, and what can be done with it. */
class BookViewModel(
    val bookId: Int,
    db: KodexDatabase,
    downloads: Downloads,
    positions: Positions,
    private val bookmarkStore: Bookmarks,
) : BooksActions(db, downloads, positions) {
    val book = db.catalog().book(bookId)
    val row = db.catalog().bookRow(bookId)
    val progress = db.catalog().progress(bookId)
    val download = db.downloads().observe(bookId)
    val bookmarks = bookmarkStore.of(bookId)

    /** Where the download is on the device. */
    fun location(): String = downloads.dir(bookId).path

    fun download() = download(listOf(bookId))

    fun removeDownload() = removeDownloads(listOf(bookId))

    fun markRead(finished: Boolean) = markRead(listOf(bookId), finished)

    fun removeBookmark(id: String) = viewModelScope.launch { bookmarkStore.remove(id) }
}
