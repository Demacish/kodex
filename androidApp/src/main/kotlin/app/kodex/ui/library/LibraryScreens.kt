package app.kodex.ui.library

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.MenuBook
import androidx.compose.material.icons.automirrored.filled.Sort
import androidx.compose.material.icons.filled.Bookmark
import androidx.compose.material.icons.filled.BookmarkBorder
import androidx.compose.material.icons.filled.Checklist
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.DoneAll
import androidx.compose.material.icons.filled.Download
import androidx.compose.material.icons.filled.DownloadForOffline
import androidx.compose.material.icons.filled.MoreVert
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.RemoveDone
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import app.kodex.R
import app.kodex.data.AppSettings
import app.kodex.data.db.BookRow
import app.kodex.data.db.DownloadState
import app.kodex.data.db.SeriesEntity
import app.kodex.data.db.SeriesRow
import app.kodex.ui.AppViewModel
import app.kodex.ui.BookKey
import app.kodex.ui.Navigator
import app.kodex.ui.components.Bar
import app.kodex.ui.components.BookCard
import app.kodex.ui.components.BookLine
import app.kodex.ui.components.Cover
import app.kodex.ui.components.DownloadButton
import app.kodex.ui.components.Empty
import app.kodex.ui.components.KodexCard
import app.kodex.ui.components.MediaBadge
import app.kodex.ui.components.Pill
import app.kodex.ui.components.ProgressStrip
import app.kodex.ui.components.coverCells
import app.kodex.ui.components.mediaKind
import app.kodex.ui.components.numberLabel
import app.kodex.ui.components.rtl
import app.kodex.ui.components.size
import app.kodex.ui.theme.KodexTheme
import org.koin.compose.viewmodel.koinViewModel
import org.koin.core.parameter.parametersOf

/** A series' books: all of them, the issues (chapters), or the collected editions (volumes). */
enum class BookKind { ALL, ISSUES, COLLECTED }

/** Which of a series' books its list shows. */
enum class BookFilter { ALL, UNREAD, DOWNLOADED }

data class SeriesUiState(
    val kind: BookKind = BookKind.ALL,
    val newestFirst: Boolean = false,
    val filter: BookFilter = BookFilter.ALL,
    val selecting: Boolean = false,
    val selected: Set<Int> = emptySet(),
    val followBusy: Boolean = false,
    val problem: Int? = null,
)

class SeriesActions(
    val back: () -> Unit = {},
    val open: (Int) -> Unit = {},
    val read: (Int) -> Unit = {},
    val follow: (Boolean) -> Unit = {},
    val downloadAll: () -> Unit = {},
    val kind: (BookKind) -> Unit = {},
    val newestFirst: (Boolean) -> Unit = {},
    val filter: (BookFilter) -> Unit = {},
    val select: (Int) -> Unit = {},
    val selecting: (Boolean) -> Unit = {},
    val markRead: (Collection<Int>, Boolean) -> Unit = { _, _ -> },
    val download: (Collection<Int>) -> Unit = {},
    val removeDownloads: (Collection<Int>) -> Unit = {},
    val pause: (Int) -> Unit = {},
    val resume: (Int) -> Unit = {},
)

@Composable
fun SeriesScreen(seriesId: Int, navigator: Navigator, app: AppViewModel) {
    val vm: SeriesViewModel = koinViewModel(key = "series-$seriesId") { parametersOf(seriesId) }
    val settings by app.settings.collectAsStateWithLifecycle()
    val series by vm.series.collectAsStateWithLifecycle(initialValue = null)
    val row by vm.row.collectAsStateWithLifecycle(initialValue = null)
    val books by vm.books.collectAsStateWithLifecycle(initialValue = emptyList())
    val busy by vm.following.collectAsStateWithLifecycle()
    val problem by vm.problem.collectAsStateWithLifecycle()
    var kind by rememberSaveable { mutableStateOf(BookKind.ALL) }
    var newestFirst by rememberSaveable { mutableStateOf(false) }
    var filter by rememberSaveable { mutableStateOf(BookFilter.ALL) }
    var selecting by rememberSaveable { mutableStateOf(false) }
    var selected by remember { mutableStateOf(emptySet<Int>()) }
    BackHandler(enabled = selecting) {
        selecting = false
        selected = emptySet()
    }
    SeriesContent(
        series, row, books, settings,
        SeriesUiState(kind, newestFirst, filter, selecting, selected, busy, problem),
        SeriesActions(
            back = navigator::back,
            open = { navigator.open(BookKey(it)) },
            read = { navigator.read(it) },
            follow = { vm.follow(it) },
            downloadAll = { vm.downloadAll() },
            kind = { kind = it },
            newestFirst = { newestFirst = it },
            filter = { filter = it },
            select = { id -> selected = if (id in selected) selected - id else selected + id },
            selecting = { on ->
                selecting = on
                if (!on) selected = emptySet()
            },
            markRead = { ids, finished -> vm.markRead(ids, finished) },
            download = { vm.download(it) },
            removeDownloads = { vm.removeDownloads(it) },
            pause = { vm.pause(it) },
            resume = { vm.resume(it) },
        ),
    )
}

/** The book to go on with: the one being read, else the first not read, else the first. */
fun nextToRead(books: List<BookRow>): BookRow? =
    books.firstOrNull { it.finished != true && (it.percent ?: 0.0) > 0 } ?: books.firstOrNull { it.finished != true } ?: books.firstOrNull()

@Composable
fun SeriesContent(
    series: SeriesEntity?,
    row: SeriesRow?,
    books: List<BookRow>,
    settings: AppSettings,
    state: SeriesUiState,
    actions: SeriesActions,
) {
    val colors = KodexTheme.colors
    Scaffold(
        topBar = {
            Bar(
                if (state.selecting) stringResource(R.string.selected_count, state.selected.size) else series?.title.orEmpty(),
                onBack = if (state.selecting) ({ actions.selecting(false) }) else actions.back,
                actions = {
                    if (state.selecting) {
                        TextButton(onClick = {
                            books.forEach { if (it.id !in state.selected) actions.select(it.id) }
                        }) { Text(stringResource(R.string.select_all)) }
                    } else {
                        IconButton(onClick = { actions.selecting(true) }, modifier = Modifier.testTag("select")) {
                            Icon(Icons.Filled.Checklist, contentDescription = stringResource(R.string.select_several))
                        }
                    }
                },
            )
        },
        bottomBar = { if (state.selecting && state.selected.isNotEmpty()) SelectionBar(state.selected, actions) },
        containerColor = colors.background,
    ) { padding ->
        if (series == null) return@Scaffold
        val issues = books.filter { it.editionType != "collected" }
        val collected = books.filter { it.editionType == "collected" }
        val kinds = issues.isNotEmpty() && collected.isNotEmpty()
        val listed = when (if (kinds) state.kind else BookKind.ALL) {
            BookKind.ALL -> books
            BookKind.ISSUES -> issues
            BookKind.COLLECTED -> collected
        }.filter {
            when (state.filter) {
                BookFilter.ALL -> true
                BookFilter.UNREAD -> it.finished != true
                BookFilter.DOWNLOADED -> it.downloadState == DownloadState.DONE
            }
        }.let { if (state.newestFirst) it.reversed() else it }
        BoxWithConstraints(Modifier.fillMaxSize().padding(padding)) {
            val wide = maxWidth >= 700.dp
            LazyColumn(Modifier.fillMaxSize().testTag("series"), contentPadding = PaddingValues(bottom = 32.dp)) {
                item(key = "hero") { Hero(series, row, books, settings, state, actions, wide) }
                item(key = "list-head") {
                    ListHead(row?.libraryType, issues.size, collected.size, kinds, state, actions)
                }
                items(listed, key = { it.id }) { book ->
                    BookLine(
                        book,
                        selecting = state.selecting,
                        selected = book.id in state.selected,
                        onClick = { if (state.selecting) actions.select(book.id) else actions.open(book.id) },
                        onLongClick = {
                            if (!state.selecting) actions.selecting(true)
                            actions.select(book.id)
                        },
                    ) {
                        if (!state.selecting) {
                            val total = book.downloadTotal ?: 0L
                            DownloadButton(
                                book.downloadState,
                                if (total > 0) (book.downloadBytes ?: 0L).toFloat() / total else null,
                                onDownload = { actions.download(listOf(book.id)) },
                                onPause = { actions.pause(book.id) },
                                onResume = { actions.resume(book.id) },
                            )
                            BookMenu(book, actions)
                        }
                    }
                }
                if (listed.isEmpty()) item(key = "none") { Empty(stringResource(R.string.nothing_matches), Modifier.height(160.dp)) }
            }
        }
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun Hero(
    series: SeriesEntity,
    row: SeriesRow?,
    books: List<BookRow>,
    settings: AppSettings,
    state: SeriesUiState,
    actions: SeriesActions,
    wide: Boolean,
) {
    val colors = KodexTheme.colors
    val libraryType = row?.libraryType
    Column(Modifier.fillMaxWidth().padding(16.dp), verticalArrangement = Arrangement.spacedBy(16.dp)) {
        Row(horizontalArrangement = Arrangement.spacedBy(16.dp)) {
            Cover(row?.firstBookId, width = if (wide) 180.dp else 124.dp, corner = 10.dp)
            Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                MediaBadge(mediaKind(libraryType, ""), stringResource(R.string.badge_series), settings.rtl(libraryType))
                Text(series.title, style = if (wide) MaterialTheme.typography.displaySmall else MaterialTheme.typography.headlineMedium,
                    color = colors.text, maxLines = 3, overflow = TextOverflow.Ellipsis)
                val authors = books.firstOrNull { it.authors.isNotBlank() }?.authors
                if (authors != null) Text(authors, style = MaterialTheme.typography.bodyLarge, color = colors.accentText, maxLines = 2)
                FlowRow(horizontalArrangement = Arrangement.spacedBy(14.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                    series.publisher?.let { Fact(stringResource(R.string.publisher), it) }
                    series.startYear?.let { Fact(stringResource(R.string.year), it.toString()) }
                    Fact(stringResource(R.string.books), books.size.toString())
                }
                series.status?.let { status ->
                    val ongoing = status.lowercase() == "ongoing"
                    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                        Box(Modifier.size(8.dp).clip(CircleShape).background(if (ongoing) colors.offline else colors.textMuted))
                        Text(stringResource(if (ongoing) R.string.status_ongoing else R.string.status_ended),
                            style = MaterialTheme.typography.labelLarge, color = if (ongoing) colors.offlineText else colors.textMuted)
                    }
                }
            }
        }
        val next = nextToRead(books)
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
            if (next != null) {
                val reading = next.finished != true && (next.percent ?: 0.0) > 0
                val everything = books.all { it.finished == true }
                Button(
                    onClick = { actions.read(next.id) },
                    modifier = Modifier.weight(1f).heightIn(min = 52.dp).testTag("series-read"),
                    shape = MaterialTheme.shapes.small,
                ) {
                    Icon(Icons.Filled.PlayArrow, contentDescription = null)
                    Spacer(Modifier.width(8.dp))
                    val number = numberLabel(next.number, next.editionType, libraryType)
                    Column {
                        Text(
                            when {
                                everything -> stringResource(R.string.read_again)
                                reading || books.any { it.finished == true } -> stringResource(R.string.continue_reading)
                                else -> stringResource(R.string.start_reading)
                            },
                            maxLines = 1, overflow = TextOverflow.Ellipsis,
                        )
                        if (number != null) {
                            Text(number, style = MaterialTheme.typography.labelMedium, maxLines = 1, overflow = TextOverflow.Ellipsis)
                        }
                    }
                }
            }
            val missing = books.count { it.downloadState == null || it.downloadState == DownloadState.FAILED }
            OutlinedButton(
                onClick = actions.downloadAll,
                enabled = missing > 0,
                modifier = Modifier.heightIn(min = 52.dp).testTag("download-all"),
                shape = MaterialTheme.shapes.small,
                border = BorderStroke(1.dp, colors.border),
                colors = ButtonDefaults.outlinedButtonColors(containerColor = colors.surface1, contentColor = colors.text),
            ) {
                Icon(Icons.Filled.DownloadForOffline, contentDescription = null, tint = colors.offlineText)
                Spacer(Modifier.width(6.dp))
                Text(stringResource(R.string.download_all))
            }
            val following = series.following
            OutlinedButton(
                onClick = { actions.follow(!following) },
                enabled = !state.followBusy,
                modifier = Modifier.heightIn(min = 52.dp).testTag("follow"),
                shape = MaterialTheme.shapes.small,
                border = BorderStroke(1.dp, if (following) colors.accent else colors.border),
                colors = ButtonDefaults.outlinedButtonColors(
                    containerColor = if (following) colors.accentSoft else colors.surface1,
                    contentColor = if (following) colors.accentText else colors.text,
                ),
            ) {
                Icon(if (following) Icons.Filled.Bookmark else Icons.Filled.BookmarkBorder, contentDescription = null)
                if (wide) {
                    Spacer(Modifier.width(6.dp))
                    Text(stringResource(if (following) R.string.following else R.string.follow))
                }
            }
        }
        state.problem?.let { Text(stringResource(it), color = colors.danger, style = MaterialTheme.typography.bodyMedium) }
        ProgressCard(books)
        series.summary?.takeIf { it.isNotBlank() }?.let { Summary(it) }
    }
}

@Composable
private fun Fact(label: String, value: String) {
    val colors = KodexTheme.colors
    Row(horizontalArrangement = Arrangement.spacedBy(4.dp)) {
        Text("$label:", style = MaterialTheme.typography.bodyMedium, color = colors.textMuted)
        Text(value, style = MaterialTheme.typography.bodyMedium, color = colors.text)
    }
}

/** How much of the series is read, and how much of it is on the device. */
@Composable
private fun ProgressCard(books: List<BookRow>) {
    val colors = KodexTheme.colors
    val read = books.count { it.finished == true }
    val downloaded = books.filter { it.downloadState == DownloadState.DONE }
    KodexCard(Modifier.fillMaxWidth().testTag("series-progress")) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Icon(Icons.AutoMirrored.Filled.MenuBook, contentDescription = null, tint = colors.textMuted, modifier = Modifier.size(18.dp))
            Spacer(Modifier.width(8.dp))
            Text(stringResource(R.string.reading_progress), style = MaterialTheme.typography.titleSmall, color = colors.text, modifier = Modifier.weight(1f))
            val percent = if (books.isEmpty()) 0 else read * 100 / books.size
            Text(stringResource(R.string.percent, percent), style = MaterialTheme.typography.titleSmall, color = colors.accentText)
            Text("  ·  " + stringResource(R.string.read_of, read, books.size), style = MaterialTheme.typography.bodyMedium, color = colors.textMuted)
        }
        Spacer(Modifier.height(10.dp))
        ProgressStrip(if (books.isEmpty()) 0f else read.toFloat() / books.size, Modifier.height(6.dp), track = colors.surface3)
        Spacer(Modifier.height(14.dp))
        Row(verticalAlignment = Alignment.CenterVertically) {
            Icon(Icons.Filled.DownloadForOffline, contentDescription = null, tint = colors.offlineText, modifier = Modifier.size(18.dp))
            Spacer(Modifier.width(8.dp))
            Text(stringResource(R.string.on_device_of, downloaded.size, books.size), style = MaterialTheme.typography.bodyMedium,
                color = colors.text, modifier = Modifier.weight(1f))
            if (downloaded.isNotEmpty()) {
                Text(
                    size(downloaded.sumOf { it.downloadBytes ?: it.fileSize }),
                    style = MaterialTheme.typography.labelMedium,
                    color = colors.offlineText,
                    modifier = Modifier.clip(CircleShape).background(colors.offlineSoft).padding(horizontal = 8.dp, vertical = 3.dp),
                )
            }
        }
    }
}

@Composable
private fun Summary(text: String) {
    val colors = KodexTheme.colors
    var open by rememberSaveable { mutableStateOf(false) }
    Column(Modifier.clip(MaterialTheme.shapes.small).clickable { open = !open }) {
        Text(text, style = MaterialTheme.typography.bodyMedium, color = colors.textMuted, maxLines = if (open) Int.MAX_VALUE else 4,
            overflow = TextOverflow.Ellipsis)
        Text(stringResource(if (open) R.string.show_less else R.string.show_more), style = MaterialTheme.typography.labelLarge,
            color = colors.accentText, modifier = Modifier.padding(top = 4.dp))
    }
}

/** Above the books: issues or collected editions, newest or oldest first, and which to show. */
@Composable
private fun ListHead(libraryType: String?, issues: Int, collected: Int, kinds: Boolean, state: SeriesUiState, actions: SeriesActions) {
    val colors = KodexTheme.colors
    val manga = libraryType?.lowercase() == "manga"
    Column(
        Modifier.fillMaxWidth().background(colors.surface1).padding(horizontal = 16.dp, vertical = 10.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            if (kinds) {
                Row(Modifier.weight(1f), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Pill(stringResource(if (manga) R.string.kind_chapters else R.string.kind_issues), state.kind == BookKind.ISSUES,
                        { actions.kind(if (state.kind == BookKind.ISSUES) BookKind.ALL else BookKind.ISSUES) }, count = issues)
                    Pill(stringResource(if (manga) R.string.kind_volumes else R.string.kind_collected), state.kind == BookKind.COLLECTED,
                        { actions.kind(if (state.kind == BookKind.COLLECTED) BookKind.ALL else BookKind.COLLECTED) }, count = collected)
                }
            } else {
                Text(stringResource(R.string.books_in_series).uppercase(), style = MaterialTheme.typography.labelMedium,
                    color = colors.textMuted, modifier = Modifier.weight(1f))
            }
            Pill(
                stringResource(if (state.newestFirst) R.string.newest_first else R.string.oldest_first),
                state.newestFirst,
                { actions.newestFirst(!state.newestFirst) },
                icon = Icons.AutoMirrored.Filled.Sort,
            )
        }
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            BookFilter.entries.forEach { f ->
                Pill(
                    stringResource(
                        when (f) {
                            BookFilter.ALL -> R.string.filter_all
                            BookFilter.UNREAD -> R.string.filter_unread
                            BookFilter.DOWNLOADED -> R.string.filter_downloaded
                        },
                    ),
                    state.filter == f,
                    { actions.filter(f) },
                )
            }
        }
    }
}

@Composable
private fun BookMenu(book: BookRow, actions: SeriesActions) {
    var open by remember { mutableStateOf(false) }
    Box {
        IconButton(onClick = { open = true }, modifier = Modifier.testTag("book-menu-${book.id}")) {
            Icon(Icons.Filled.MoreVert, contentDescription = stringResource(R.string.more))
        }
        DropdownMenu(expanded = open, onDismissRequest = { open = false }) {
            DropdownMenuItem(text = { Text(stringResource(R.string.read)) }, onClick = { open = false; actions.read(book.id) },
                leadingIcon = { Icon(Icons.Filled.PlayArrow, contentDescription = null) })
            DropdownMenuItem(text = { Text(stringResource(R.string.details)) }, onClick = { open = false; actions.open(book.id) },
                leadingIcon = { Icon(Icons.AutoMirrored.Filled.MenuBook, contentDescription = null) })
            val finished = book.finished == true
            DropdownMenuItem(
                text = { Text(stringResource(if (finished) R.string.mark_unread else R.string.mark_read)) },
                onClick = { open = false; actions.markRead(listOf(book.id), !finished) },
                leadingIcon = { Icon(if (finished) Icons.Filled.RemoveDone else Icons.Filled.DoneAll, contentDescription = null) },
            )
            if (book.downloadState != null) {
                DropdownMenuItem(text = { Text(stringResource(R.string.remove_download)) },
                    onClick = { open = false; actions.removeDownloads(listOf(book.id)) },
                    leadingIcon = { Icon(Icons.Filled.Delete, contentDescription = null) })
            } else {
                DropdownMenuItem(text = { Text(stringResource(R.string.download)) }, onClick = { open = false; actions.download(listOf(book.id)) },
                    leadingIcon = { Icon(Icons.Filled.Download, contentDescription = null) })
            }
        }
    }
}

/** What can be done with the chosen books. */
@Composable
private fun SelectionBar(selected: Set<Int>, actions: SeriesActions) {
    val colors = KodexTheme.colors
    Surface(color = colors.surface2, border = BorderStroke(1.dp, colors.border), modifier = Modifier.testTag("selection-bar")) {
        Row(
            Modifier.fillMaxWidth().navigationBarsPadding().padding(horizontal = 8.dp, vertical = 6.dp),
            horizontalArrangement = Arrangement.SpaceEvenly,
        ) {
            Choice(Icons.Filled.DoneAll, stringResource(R.string.mark_read_short)) {
                actions.markRead(selected, true)
                actions.selecting(false)
            }
            Choice(Icons.Filled.RemoveDone, stringResource(R.string.mark_unread_short)) {
                actions.markRead(selected, false)
                actions.selecting(false)
            }
            Choice(Icons.Filled.Download, stringResource(R.string.download)) {
                actions.download(selected)
                actions.selecting(false)
            }
            Choice(Icons.Filled.Delete, stringResource(R.string.remove_short)) {
                actions.removeDownloads(selected)
                actions.selecting(false)
            }
            Choice(Icons.Filled.Close, stringResource(R.string.cancel)) { actions.selecting(false) }
        }
    }
}

@Composable
private fun Choice(icon: androidx.compose.ui.graphics.vector.ImageVector, label: String, onClick: () -> Unit) {
    val colors = KodexTheme.colors
    Column(
        Modifier.clip(RoundedCornerShape(12.dp)).clickable(onClick = onClick).padding(horizontal = 10.dp, vertical = 6.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Icon(icon, contentDescription = null, tint = colors.text)
        Text(label, style = MaterialTheme.typography.labelMedium, color = colors.textMuted)
    }
}

/** A collection's books, as covers. */
@Composable
fun CollectionScreen(collectionId: Int, name: String, navigator: Navigator, app: AppViewModel) {
    val vm: LibraryViewModel = koinViewModel()
    val settings by app.settings.collectAsStateWithLifecycle()
    val books by remember(collectionId) { vm.collectionBooks(collectionId) }.collectAsStateWithLifecycle(initialValue = emptyList())
    CollectionContent(name, books, settings, navigator::back) { navigator.open(BookKey(it)) }
}

@Composable
fun CollectionContent(name: String, books: List<BookRow>, settings: AppSettings, onBack: () -> Unit, onOpen: (Int) -> Unit) {
    Scaffold(topBar = { Bar(name, onBack = onBack) }, containerColor = KodexTheme.colors.background) { padding ->
        if (books.isEmpty()) {
            Empty(stringResource(R.string.collection_empty), Modifier.padding(padding))
            return@Scaffold
        }
        LazyVerticalGrid(
            columns = coverCells(settings.density),
            contentPadding = PaddingValues(16.dp, padding.calculateTopPadding() + 8.dp, 16.dp, padding.calculateBottomPadding() + 24.dp),
            horizontalArrangement = Arrangement.spacedBy(12.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp),
            modifier = Modifier.fillMaxSize().testTag("collection"),
        ) {
            items(books, key = { it.id }) { BookCard(it, settings, { onOpen(it.id) }) }
        }
    }
}
