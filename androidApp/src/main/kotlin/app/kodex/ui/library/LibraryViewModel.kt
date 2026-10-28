package app.kodex.ui.library

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import app.kodex.data.Position
import app.kodex.data.Positions
import app.kodex.data.db.BookRow
import app.kodex.data.db.KodexDatabase
import app.kodex.download.Downloads
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.flatMapLatest
import kotlinx.coroutines.flow.flowOf
import kotlinx.coroutines.launch

/** The catalog on the device, for the lists (all of it works offline). */
class LibraryViewModel(db: KodexDatabase) : ViewModel() {
    private val catalog = db.catalog()

    val libraries = catalog.libraries()
    val continueReading = catalog.continueReading()
    val collections = catalog.collections()

    fun series(libraryId: Int) = catalog.seriesIn(libraryId)

    fun looseBooks(libraryId: Int) = catalog.looseBooks(libraryId)

    fun seriesInfo(id: Int) = catalog.series(id)

    fun books(seriesId: Int) = catalog.booksIn(seriesId)

    fun collectionBooks(id: Int) = catalog.collectionBooks(id)

    val query = MutableStateFlow("")

    @OptIn(ExperimentalCoroutinesApi::class)
    val results: Flow<List<BookRow>> = query.flatMapLatest { text ->
        if (text.isBlank()) flowOf(emptyList()) else catalog.searchBooks(text.trim())
    }
}

/** One book: its details, position and download, and what can be done with it. */
class BookViewModel(
    val bookId: Int,
    private val db: KodexDatabase,
    private val downloads: Downloads,
    private val positions: Positions,
) : ViewModel() {
    val book = db.catalog().book(bookId)
    val progress = db.catalog().progress(bookId)
    val download = db.downloads().observe(bookId)

    fun download() = viewModelScope.launch { db.catalog().bookNow(bookId)?.let { downloads.request(it) } }

    fun removeDownload() = viewModelScope.launch { downloads.remove(bookId) }

    fun markRead(finished: Boolean) = viewModelScope.launch {
        positions.record(bookId, if (finished) Position(null, null, 100.0, true) else Position(null, null, 0.0, false))
    }
}
