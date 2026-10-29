package app.kodex.ui.components

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import app.kodex.R
import app.kodex.data.AppSettings
import app.kodex.data.ImageMode
import app.kodex.data.db.BookRow
import app.kodex.data.db.ContinueRow
import app.kodex.data.db.DownloadState
import app.kodex.data.db.SeriesRow
import app.kodex.ui.theme.KodexTheme

/** Whether books in a library of [libraryType] open right to left. */
fun AppSettings.rtl(libraryType: String?): Boolean = modeFor(libraryType) == ImageMode.PAGED_RTL

/** The line under a book's title: its number and series, or its authors. */
@Composable
fun bookLine(book: BookRow): String? =
    listOfNotNull(numberLabel(book.number, book.editionType, book.libraryType), book.seriesTitle ?: book.authors.ifBlank { null })
        .joinToString(" · ").ifBlank { null }

@Composable
fun BookCard(book: BookRow, settings: AppSettings, onClick: () -> Unit, modifier: Modifier = Modifier, width: Dp? = null) {
    val total = book.downloadTotal ?: 0L
    CoverCard(
        bookId = book.id,
        title = book.title,
        subtitle = bookLine(book),
        marks = CoverMarks(
            kind = mediaKind(book.libraryType, book.format),
            format = book.format,
            rtl = settings.rtl(book.libraryType),
            progress = book.percent?.let { (it / 100).toFloat() },
            finished = book.finished == true,
            download = book.downloadState,
            downloadFraction = if (total > 0) ((book.downloadBytes ?: 0L).toFloat() / total) else null,
        ),
        onClick = onClick,
        modifier = modifier.testTag("book-${book.id}"),
        width = width,
    )
}

@Composable
fun SeriesCard(series: SeriesRow, settings: AppSettings, onClick: () -> Unit, modifier: Modifier = Modifier, width: Dp? = null) {
    val started = series.readCount > 0 || series.startedCount > 0
    CoverCard(
        bookId = series.firstBookId,
        title = series.title,
        subtitle = stringResource(R.string.series_read, series.readCount, series.bookCount),
        marks = CoverMarks(
            kind = mediaKind(series.libraryType, ""),
            format = stringResource(R.string.badge_series),
            rtl = settings.rtl(series.libraryType),
            progress = if (started && series.bookCount > 0) series.readCount.toFloat() / series.bookCount else null,
            finished = series.bookCount > 0 && series.readCount == series.bookCount,
            download = if (series.bookCount > 0 && series.downloadedCount == series.bookCount) DownloadState.DONE else null,
        ),
        onClick = onClick,
        modifier = modifier.testTag("series-${series.id}"),
        width = width,
    )
}

/** A book being read, large: where in it on the cover, the progress along its foot. */
@Composable
fun ContinueCard(book: ContinueRow, settings: AppSettings, width: Dp, onClick: () -> Unit) {
    val colors = KodexTheme.colors
    val pages = book.pageCount
    val fraction = (book.percent / 100).toFloat()
    CoverCard(
        bookId = book.id,
        title = book.title,
        subtitle = listOfNotNull(book.seriesTitle, numberLabel(book.number, "issue", book.libraryType)).joinToString(" · ").ifBlank { null },
        marks = CoverMarks(
            kind = mediaKind(book.libraryType, book.format),
            format = book.format,
            rtl = settings.rtl(book.libraryType),
            download = book.downloadState,
        ),
        onClick = onClick,
        modifier = Modifier.testTag("continue-${book.id}"),
        width = width,
        overlay = {
            Column(Modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                    Text(
                        if (pages != null && pages > 0) stringResource(R.string.page_of_short, (fraction * pages).toInt().coerceIn(1, pages), pages) else "",
                        style = MaterialTheme.typography.labelMedium, color = Color(0xFFF3F4F6), maxLines = 1, overflow = TextOverflow.Ellipsis,
                    )
                    Text(stringResource(R.string.percent, book.percent.toInt()), style = MaterialTheme.typography.labelMedium, color = colors.accent)
                }
                ProgressStrip(fraction, track = Color(0x66FFFFFF))
            }
        },
    )
}
