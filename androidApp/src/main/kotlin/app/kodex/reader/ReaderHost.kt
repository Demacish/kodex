package app.kodex.reader

import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.graphics.Color
import app.kodex.data.AppSettings
import app.kodex.data.ImageMode
import app.kodex.data.Position
import app.kodex.data.db.BookmarkEntity

/**
 * What a reader gets from the activity around it: how to title the book, the direction it
 * starts in, its bookmarks, the light, and a way to keep a setting for the next book.
 */
class ReaderHost(
    val title: ReaderTitle,
    val mode: ImageMode,
    val bookmarks: List<BookmarkEntity>,
    val addBookmark: (Position) -> Unit,
    val removeBookmark: (String) -> Unit,
    val light: LightControls,
    val update: ((AppSettings) -> AppSettings) -> Unit,
) {
    /** The bar's bookmark controls for a place: [here] tells which bookmarks are at it. */
    fun bookmarkControls(here: (BookmarkEntity) -> Boolean, at: () -> Position, open: (BookmarkEntity) -> Unit): BookmarkControls {
        val marks = bookmarks.filter(here)
        return BookmarkControls(
            marked = marks.isNotEmpty(),
            list = bookmarks,
            toggle = { if (marks.isNotEmpty()) marks.forEach { removeBookmark(it.id) } else addBookmark(at()) },
            open = open,
            remove = { removeBookmark(it.id) },
        )
    }
}

/** The colour of words over the pages' background (white on black, the theme's text otherwise). */
val LocalReaderInk = staticCompositionLocalOf { Color.White }
