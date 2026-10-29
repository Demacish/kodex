package app.kodex.ui.library

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.MenuBook
import androidx.compose.material.icons.filled.Bookmark
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.DoneAll
import androidx.compose.material.icons.filled.Download
import androidx.compose.material.icons.filled.Pause
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.RemoveDone
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import app.kodex.R
import app.kodex.data.AppSettings
import app.kodex.data.db.BookEntity
import app.kodex.data.db.BookRow
import app.kodex.data.db.BookmarkEntity
import app.kodex.data.db.DownloadEntity
import app.kodex.data.db.DownloadKinds
import app.kodex.data.db.DownloadState
import app.kodex.data.db.ProgressEntity
import app.kodex.download.FILE_FORMATS
import app.kodex.ui.AppViewModel
import app.kodex.ui.Navigator
import app.kodex.ui.SeriesKey
import app.kodex.ui.components.Bar
import app.kodex.ui.components.Cover
import app.kodex.ui.components.KodexCard
import app.kodex.ui.components.MediaBadge
import app.kodex.ui.components.ProgressStrip
import app.kodex.ui.components.SectionHeader
import app.kodex.ui.components.mediaKind
import app.kodex.ui.components.numberLabel
import app.kodex.ui.components.readable
import app.kodex.ui.components.rtl
import app.kodex.ui.components.size
import app.kodex.ui.theme.KodexTheme
import java.util.Locale
import org.koin.compose.viewmodel.koinViewModel
import org.koin.core.parameter.parametersOf

class BookActions(
    val back: () -> Unit = {},
    val read: (String?, String?) -> Unit = { _, _ -> },
    val openSeries: (Int) -> Unit = {},
    val download: () -> Unit = {},
    val removeDownload: () -> Unit = {},
    val pause: () -> Unit = {},
    val resume: () -> Unit = {},
    val markRead: (Boolean) -> Unit = {},
    val removeBookmark: (String) -> Unit = {},
)

@Composable
fun BookScreen(bookId: Int, navigator: Navigator, app: AppViewModel) {
    val vm: BookViewModel = koinViewModel(key = "book-$bookId") { parametersOf(bookId) }
    val settings by app.settings.collectAsStateWithLifecycle()
    val book by vm.book.collectAsStateWithLifecycle(initialValue = null)
    val row by vm.row.collectAsStateWithLifecycle(initialValue = null)
    val progress by vm.progress.collectAsStateWithLifecycle(initialValue = null)
    val download by vm.download.collectAsStateWithLifecycle(initialValue = null)
    val bookmarks by vm.bookmarks.collectAsStateWithLifecycle(initialValue = emptyList())
    BookContent(
        book, row, progress, download, bookmarks, download?.takeIf { it.state == DownloadState.DONE }?.let { vm.location() }, settings,
        BookActions(
            back = navigator::back,
            read = { position, kind -> navigator.read(bookId, position, kind) },
            openSeries = { navigator.open(SeriesKey(it)) },
            download = { vm.download() },
            removeDownload = { vm.removeDownload() },
            pause = { vm.pause(bookId) },
            resume = { vm.resume(bookId) },
            markRead = { vm.markRead(it) },
            removeBookmark = { vm.removeBookmark(it) },
        ),
    )
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
fun BookContent(
    book: BookEntity?,
    row: BookRow?,
    progress: ProgressEntity?,
    download: DownloadEntity?,
    bookmarks: List<BookmarkEntity>,
    location: String?,
    settings: AppSettings,
    actions: BookActions,
) {
    val colors = KodexTheme.colors
    Scaffold(topBar = { Bar(book?.title.orEmpty(), onBack = actions.back) }, containerColor = colors.background) { padding ->
        if (book == null) return@Scaffold
        BoxWithConstraints(Modifier.fillMaxSize().padding(padding), contentAlignment = Alignment.TopCenter) {
            val wide = maxWidth >= 600.dp
            Column(
                Modifier.readable().verticalScroll(rememberScrollState()).padding(16.dp).testTag("book"),
                verticalArrangement = Arrangement.spacedBy(16.dp),
            ) {
                val libraryType = row?.libraryType
                Row(horizontalArrangement = Arrangement.spacedBy(16.dp)) {
                    Cover(book.id, width = if (wide) 180.dp else 124.dp, corner = 10.dp)
                    Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                        MediaBadge(mediaKind(libraryType, book.format), book.format, settings.rtl(libraryType))
                        Text(book.title, style = MaterialTheme.typography.headlineMedium, color = colors.text, maxLines = 4,
                            overflow = TextOverflow.Ellipsis)
                        val seriesId = book.seriesId
                        val seriesTitle = row?.seriesTitle
                        if (seriesId != null && seriesTitle != null) {
                            Text(
                                listOfNotNull(seriesTitle, numberLabel(book.number, book.editionType, libraryType)).joinToString(" · "),
                                style = MaterialTheme.typography.bodyLarge,
                                color = colors.accentText,
                                modifier = Modifier.clip(MaterialTheme.shapes.small).clickable { actions.openSeries(seriesId) }
                                    .padding(vertical = 2.dp).testTag("book-series"),
                            )
                        }
                        if (book.authors.isNotBlank()) Text(book.authors, style = MaterialTheme.typography.bodyMedium, color = colors.text)
                        Text(
                            listOfNotNull(
                                book.format.uppercase(Locale.ROOT),
                                book.pageCount?.let { stringResource(R.string.pages_count, it) },
                                size(book.fileSize),
                                book.publishedYear?.toString(),
                                book.language?.uppercase(Locale.ROOT),
                            ).joinToString(" · "),
                            style = MaterialTheme.typography.bodySmall,
                            color = colors.textMuted,
                        )
                    }
                }

                val percent = progress?.percent ?: 0.0
                val finished = progress?.finished == true
                val state = download?.state
                val canRead = state == DownloadState.DONE || book.format !in FILE_FORMATS || book.format == "cbz"
                FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Button(
                        onClick = { actions.read(null, null) },
                        enabled = canRead,
                        modifier = Modifier.heightIn(min = 52.dp).testTag("read"),
                        shape = MaterialTheme.shapes.small,
                    ) {
                        Icon(Icons.Filled.PlayArrow, contentDescription = null)
                        Spacer(Modifier.width(8.dp))
                        Text(
                            when {
                                finished -> stringResource(R.string.read_again)
                                percent > 0 -> stringResource(R.string.continue_percent, percent.toInt())
                                else -> stringResource(R.string.read)
                            },
                        )
                    }
                    val outlined = ButtonDefaults.outlinedButtonColors(containerColor = colors.surface1, contentColor = colors.text)
                    val border = BorderStroke(1.dp, colors.border)
                    when (state) {
                        DownloadState.DONE -> OutlinedButton(actions.removeDownload, Modifier.heightIn(min = 52.dp).testTag("remove-download"),
                            shape = MaterialTheme.shapes.small, colors = outlined, border = border) {
                            Icon(Icons.Filled.Delete, contentDescription = null)
                            Spacer(Modifier.width(8.dp))
                            Text(stringResource(R.string.remove_download))
                        }
                        DownloadState.QUEUED, DownloadState.RUNNING -> OutlinedButton(actions.pause, Modifier.heightIn(min = 52.dp).testTag("pause"),
                            shape = MaterialTheme.shapes.small, colors = outlined, border = border) {
                            Icon(Icons.Filled.Pause, contentDescription = null)
                            Spacer(Modifier.width(8.dp))
                            Text(stringResource(R.string.pause))
                        }
                        DownloadState.PAUSED, DownloadState.FAILED -> OutlinedButton(actions.resume, Modifier.heightIn(min = 52.dp).testTag("resume"),
                            shape = MaterialTheme.shapes.small, colors = outlined, border = border) {
                            Icon(Icons.Filled.Download, contentDescription = null, tint = colors.offlineText)
                            Spacer(Modifier.width(8.dp))
                            Text(stringResource(if (state == DownloadState.FAILED) R.string.retry else R.string.resume))
                        }
                        null -> OutlinedButton(actions.download, Modifier.heightIn(min = 52.dp).testTag("download"),
                            shape = MaterialTheme.shapes.small, colors = outlined, border = border) {
                            Icon(Icons.Filled.Download, contentDescription = null, tint = colors.offlineText)
                            Spacer(Modifier.width(8.dp))
                            Text(stringResource(R.string.download))
                        }
                    }
                    TextButton(onClick = { actions.markRead(!finished) }, modifier = Modifier.heightIn(min = 52.dp)) {
                        Icon(if (finished) Icons.Filled.RemoveDone else Icons.Filled.DoneAll, contentDescription = null)
                        Spacer(Modifier.width(8.dp))
                        Text(stringResource(if (finished) R.string.mark_unread else R.string.mark_read))
                    }
                }
                if (!canRead) Text(stringResource(R.string.download_to_read), style = MaterialTheme.typography.bodySmall, color = colors.textMuted)

                if (percent > 0 || finished || download != null) {
                    KodexCard(Modifier.fillMaxWidth()) {
                        if (percent > 0 || finished) {
                            Text(
                                if (finished) stringResource(R.string.finished) else stringResource(R.string.read_percent, percent.toInt()),
                                style = MaterialTheme.typography.titleSmall, color = colors.text,
                            )
                            Spacer(Modifier.height(8.dp))
                            ProgressStrip(if (finished) 1f else (percent / 100).toFloat(), Modifier.height(6.dp), track = colors.surface3)
                        }
                        download?.let { d ->
                            if (percent > 0 || finished) Spacer(Modifier.height(14.dp))
                            DownloadLine(d)
                        }
                    }
                }

                val genres = book.genres.split(",").map { it.trim() }.filter { it.isNotEmpty() }
                if (genres.isNotEmpty()) {
                    FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                        genres.forEach { genre ->
                            Text(
                                genre,
                                style = MaterialTheme.typography.labelMedium,
                                color = colors.text,
                                modifier = Modifier.clip(MaterialTheme.shapes.extraSmall).background(colors.surface3)
                                    .padding(horizontal = 8.dp, vertical = 4.dp),
                            )
                        }
                    }
                }
                book.summary?.takeIf { it.isNotBlank() }?.let { Text(it, style = MaterialTheme.typography.bodyMedium, color = colors.textMuted) }

                if (bookmarks.isNotEmpty()) {
                    SectionHeader(stringResource(R.string.bookmarks))
                    KodexCard(Modifier.fillMaxWidth().testTag("bookmarks"), padding = androidx.compose.foundation.layout.PaddingValues(vertical = 4.dp)) {
                        bookmarks.forEach { mark ->
                            Row(
                                Modifier.fillMaxWidth().clickable { actions.read(mark.position, mark.locatorKind) }
                                    .padding(start = 16.dp, end = 4.dp, top = 4.dp, bottom = 4.dp),
                                verticalAlignment = Alignment.CenterVertically,
                            ) {
                                Icon(Icons.Filled.Bookmark, contentDescription = null, tint = colors.accentText, modifier = Modifier.size(18.dp))
                                Spacer(Modifier.width(12.dp))
                                Column(Modifier.weight(1f)) {
                                    Text(bookmarkLabel(mark), style = MaterialTheme.typography.titleSmall, color = colors.text)
                                    Text(stringResource(R.string.percent_in, mark.percent.toInt()), style = MaterialTheme.typography.bodySmall,
                                        color = colors.textMuted)
                                }
                                IconButton(onClick = { actions.removeBookmark(mark.id) }) {
                                    Icon(Icons.Filled.Delete, contentDescription = stringResource(R.string.remove_bookmark), tint = colors.textMuted)
                                }
                            }
                        }
                    }
                }

                FileCard(book, download, location)
            }
        }
    }
}

@Composable
private fun DownloadLine(d: DownloadEntity) {
    val colors = KodexTheme.colors
    when (d.state) {
        DownloadState.RUNNING, DownloadState.QUEUED, DownloadState.PAUSED -> {
            val fraction = if (d.total > 0) (d.bytes.toFloat() / d.total).coerceIn(0f, 1f) else 0f
            Text(
                stringResource(
                    when (d.state) {
                        DownloadState.QUEUED -> R.string.download_waiting
                        DownloadState.PAUSED -> R.string.download_paused_size
                        else -> R.string.downloading_size
                    },
                    size(d.bytes), size(d.total),
                ),
                style = MaterialTheme.typography.bodyMedium, color = colors.text,
            )
            Spacer(Modifier.height(8.dp))
            Box(Modifier.fillMaxWidth().height(6.dp).clip(CircleShape).background(colors.surface3).testTag("download-progress")) {
                Box(Modifier.fillMaxWidth(fraction).height(6.dp).clip(CircleShape).background(colors.offline))
            }
        }
        DownloadState.FAILED -> Text(stringResource(R.string.download_failed, d.error.orEmpty()), color = colors.danger,
            style = MaterialTheme.typography.bodyMedium)
        DownloadState.DONE -> Row(verticalAlignment = Alignment.CenterVertically) {
            Box(Modifier.size(8.dp).clip(CircleShape).background(colors.offline))
            Spacer(Modifier.width(8.dp))
            Text(
                stringResource(if (d.kind == DownloadKinds.FILE) R.string.downloaded_verified else R.string.downloaded_pages, size(d.bytes)),
                style = MaterialTheme.typography.bodyMedium, color = colors.offlineText,
            )
        }
    }
}

/** Which file the book is: where it lies on the server, and where its download is on the device. */
@Composable
private fun FileCard(book: BookEntity, download: DownloadEntity?, location: String?) {
    val colors = KodexTheme.colors
    KodexCard(Modifier.fillMaxWidth().testTag("file")) {
        Text(stringResource(R.string.file_on_server), style = MaterialTheme.typography.labelMedium, color = colors.textMuted)
        Spacer(Modifier.height(4.dp))
        SelectionContainer {
            Text(book.filePath.ifBlank { stringResource(R.string.file_unknown) }, style = MaterialTheme.typography.bodySmall,
                fontFamily = FontFamily.Monospace, color = colors.text, modifier = Modifier.testTag("file-path"))
        }
        if (location != null && download != null) {
            Spacer(Modifier.height(12.dp))
            Text(stringResource(if (download.onCard) R.string.file_on_card else R.string.file_on_device), style = MaterialTheme.typography.labelMedium,
                color = colors.textMuted)
            Spacer(Modifier.height(4.dp))
            SelectionContainer {
                Text(location, style = MaterialTheme.typography.bodySmall, fontFamily = FontFamily.Monospace, color = colors.text)
            }
            download.sha256?.let {
                Spacer(Modifier.height(12.dp))
                Text(stringResource(R.string.file_checksum), style = MaterialTheme.typography.labelMedium, color = colors.textMuted)
                Spacer(Modifier.height(4.dp))
                SelectionContainer {
                    Text(it, style = MaterialTheme.typography.bodySmall, fontFamily = FontFamily.Monospace, color = colors.text)
                }
            }
        }
    }
}

/** Where a bookmark is: a page, or a chapter in an EPUB. */
@Composable
fun bookmarkLabel(mark: BookmarkEntity): String = when (mark.locatorKind) {
    "page" -> stringResource(R.string.reader_page, (mark.position.toIntOrNull() ?: 0) + 1)
    "pdf" -> stringResource(R.string.reader_page, mark.position.toIntOrNull() ?: 1)
    else -> mark.chapter ?: stringResource(R.string.percent_in, mark.percent.toInt())
}
