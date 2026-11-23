package app.kodex.ui.read

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
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Bolt
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material3.Button
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
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
import app.kodex.data.db.CollectionEntity
import app.kodex.data.db.ContinueRow
import app.kodex.data.db.DownloadState
import app.kodex.ui.AppViewModel
import app.kodex.ui.BookKey
import app.kodex.ui.CollectionKey
import app.kodex.ui.LibraryHomeKey
import app.kodex.ui.Navigator
import app.kodex.ui.SettingsKey
import app.kodex.ui.components.BookCard
import app.kodex.ui.components.BrandBar
import app.kodex.ui.components.ContinueCard
import app.kodex.ui.components.Cover
import app.kodex.ui.components.EmptyCatalog
import app.kodex.ui.components.KodexCard
import app.kodex.ui.components.MediaBadge
import app.kodex.ui.components.Overline
import app.kodex.ui.components.PageHeading
import app.kodex.ui.components.Pill
import app.kodex.ui.components.ProgressStrip
import app.kodex.ui.components.SectionHeader
import app.kodex.ui.components.mediaKind
import app.kodex.ui.components.numberLabel
import app.kodex.ui.components.rtl
import app.kodex.ui.components.syncLine
import app.kodex.ui.library.LibraryViewModel
import app.kodex.ui.theme.KodexTheme
import org.koin.compose.viewmodel.koinViewModel

data class ReadState(
    val reading: List<ContinueRow> = emptyList(),
    /** In series being read through: the next book, when none is half read. */
    val next: List<BookRow> = emptyList(),
    val recent: List<BookRow> = emptyList(),
    val collections: List<CollectionEntity> = emptyList(),
    /** When the catalog was last brought up to date, and what is waiting to be sent. */
    val synced: String? = null,
    /** Whether there is a library at all (else the first sync, or its problem, is shown). */
    val hasLibrary: Boolean = true,
)

class ReadActions(
    val read: (Int) -> Unit = {},
    val openBook: (Int) -> Unit = {},
    val openCollection: (Int, String) -> Unit = { _, _ -> },
    val toLibrary: () -> Unit = {},
    val account: () -> Unit = {},
)

/** Läs: the book being read, large, the others being read, the next in series read through, what came last, and the collections. */
@Composable
fun ReadScreen(navigator: Navigator, app: AppViewModel) {
    val vm: LibraryViewModel = koinViewModel()
    val settings by app.settings.collectAsStateWithLifecycle()
    val libraries by vm.libraries.collectAsStateWithLifecycle(initialValue = emptyList())
    val reading by vm.continueReading.collectAsStateWithLifecycle(initialValue = emptyList())
    val next by vm.nextInSeries.collectAsStateWithLifecycle(initialValue = emptyList())
    val recent by vm.recentlyAdded.collectAsStateWithLifecycle(initialValue = emptyList())
    val collections by vm.collections.collectAsStateWithLifecycle(initialValue = emptyList())
    ReadContent(
        ReadState(reading, next, recent, collections, syncLine(app), hasLibrary = libraries.isNotEmpty()),
        settings,
        ReadActions(
            read = { navigator.read(it) },
            openBook = { navigator.open(BookKey(it)) },
            openCollection = { id, name -> navigator.open(CollectionKey(id, name)) },
            toLibrary = { navigator.switchTo(LibraryHomeKey) },
            account = { navigator.switchTo(SettingsKey) },
        ),
        empty = { EmptyCatalog(stringResource(R.string.library_empty), app, it) },
    )
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
fun ReadContent(state: ReadState, settings: AppSettings, actions: ReadActions, empty: @Composable (Modifier) -> Unit) {
    val colors = KodexTheme.colors
    Scaffold(
        topBar = { BrandBar(stringResource(R.string.tab_read), onAccount = actions.account) },
        containerColor = colors.background,
    ) { padding ->
        if (!state.hasLibrary) {
            empty(Modifier.padding(padding))
            return@Scaffold
        }
        BoxWithConstraints(Modifier.fillMaxSize().padding(padding)) {
            // A tablet puts the book being read and the others beside each other.
            val wide = maxWidth >= 840.dp
            val active = state.reading.firstOrNull()
            val beside = if (wide) state.reading.drop(1).take(4) else emptyList()
            val shelf = state.reading.drop(1 + beside.size)
            LazyColumn(
                contentPadding = PaddingValues(start = if (wide) 24.dp else 16.dp, end = if (wide) 24.dp else 16.dp, top = 4.dp, bottom = 32.dp),
                verticalArrangement = Arrangement.spacedBy(16.dp),
                modifier = Modifier.fillMaxSize().testTag("read"),
            ) {
                item("heading") { PageHeading(stringResource(R.string.read_title), line = state.synced) }
                if (active == null) {
                    item("nothing") { NothingYet(actions) }
                } else {
                    item("active") {
                        if (wide) {
                            Row(horizontalArrangement = Arrangement.spacedBy(16.dp)) {
                                ActiveCard(active, settings, actions, Modifier.weight(1.4f), large = true)
                                if (beside.isNotEmpty()) Beside(beside, actions, Modifier.weight(1f))
                            }
                        } else {
                            ActiveCard(active, settings, actions)
                        }
                    }
                }
                if (shelf.isNotEmpty()) {
                    item("reading-title") { SectionHeader(stringResource(R.string.continue_reading), count = shelf.size) }
                    item("reading") {
                        LazyRow(horizontalArrangement = Arrangement.spacedBy(14.dp), modifier = Modifier.testTag("home")) {
                            items(shelf, key = { it.id }) { book ->
                                ContinueCard(book, settings, width = if (wide) 180.dp else 150.dp) { actions.read(book.id) }
                            }
                        }
                    }
                }
                if (state.next.isNotEmpty()) {
                    item("next-title") { SectionHeader(stringResource(R.string.reader_next), count = state.next.size) }
                    item("next") {
                        LazyRow(horizontalArrangement = Arrangement.spacedBy(14.dp), modifier = Modifier.testTag("next-in-series")) {
                            items(state.next, key = { "n${it.id}" }) { book ->
                                BookCard(book, settings, { actions.openBook(book.id) }, width = if (wide) 150.dp else 120.dp)
                            }
                        }
                    }
                }
                if (state.recent.isNotEmpty()) {
                    item("recent-title") { SectionHeader(stringResource(R.string.recently_added), mark = colors.offline) }
                    item("recent") {
                        LazyRow(horizontalArrangement = Arrangement.spacedBy(14.dp)) {
                            items(state.recent.take(20), key = { "r${it.id}" }) { book ->
                                BookCard(book, settings, { actions.openBook(book.id) }, width = if (wide) 150.dp else 120.dp)
                            }
                        }
                    }
                }
                if (state.collections.isNotEmpty()) {
                    item("collections-title") { SectionHeader(stringResource(R.string.collections)) }
                    item("collections") {
                        FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                            state.collections.forEach { collection ->
                                Pill(collection.name, false, { actions.openCollection(collection.id, collection.name) })
                            }
                        }
                    }
                }
            }
        }
    }
}

/** The book being read: its cover, where in it, how far, whether it is on the device, and "Fortsätt". */
@Composable
private fun ActiveCard(book: ContinueRow, settings: AppSettings, actions: ReadActions, modifier: Modifier = Modifier, large: Boolean = false) {
    val colors = KodexTheme.colors
    val fraction = (book.percent / 100).toFloat().coerceIn(0f, 1f)
    val pages = book.pageCount
    KodexCard(
        modifier.fillMaxWidth().clip(MaterialTheme.shapes.medium).clickable { actions.read(book.id) }.testTag("active-${book.id}"),
        padding = PaddingValues(16.dp),
    ) {
        Row(horizontalArrangement = Arrangement.spacedBy(16.dp)) {
            Box {
                Cover(book.id, width = if (large) 140.dp else 96.dp)
                MediaBadge(mediaKind(book.libraryType, book.format), book.format, settings.rtl(book.libraryType),
                    Modifier.align(Alignment.TopStart).padding(5.dp))
            }
            Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                Row(
                    Modifier.clip(CircleShape).background(colors.accentSoft).padding(horizontal = 8.dp, vertical = 3.dp),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(4.dp),
                ) {
                    Icon(Icons.Filled.Bolt, contentDescription = null, tint = colors.accentText, modifier = Modifier.size(12.dp))
                    Overline(stringResource(R.string.read_active), color = colors.accentText)
                }
                Text(book.seriesTitle ?: book.title, style = if (large) MaterialTheme.typography.headlineSmall else MaterialTheme.typography.titleLarge,
                    color = colors.text, maxLines = 2, overflow = TextOverflow.Ellipsis)
                val number = numberLabel(book.number, "issue", book.libraryType)
                val line = listOfNotNull(number, book.title.takeIf { book.seriesTitle != null }).joinToString(" · ")
                if (line.isNotBlank()) {
                    Text(line, style = MaterialTheme.typography.bodyMedium, color = colors.textMuted, maxLines = 2, overflow = TextOverflow.Ellipsis)
                }
                Spacer(Modifier.height(2.dp))
                Text(
                    if (pages != null && pages > 0) {
                        stringResource(R.string.page_of, (fraction * pages).toInt().coerceIn(1, pages), pages)
                    } else {
                        stringResource(R.string.read_percent, book.percent.toInt())
                    },
                    style = MaterialTheme.typography.labelMedium, color = colors.textMuted,
                )
                ProgressStrip(fraction, track = colors.surface3)
            }
        }
        Spacer(Modifier.height(14.dp))
        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
            if (book.downloadState == DownloadState.DONE) {
                Icon(Icons.Filled.CheckCircle, contentDescription = null, tint = colors.offline, modifier = Modifier.size(16.dp))
                Spacer(Modifier.size(6.dp))
                Text(stringResource(R.string.ready_offline), style = MaterialTheme.typography.labelMedium, color = colors.offlineText)
            }
            Spacer(Modifier.weight(1f))
            Button(onClick = { actions.read(book.id) }, modifier = Modifier.testTag("continue-active")) {
                Icon(Icons.Filled.PlayArrow, contentDescription = null, modifier = Modifier.size(18.dp))
                Spacer(Modifier.size(6.dp))
                Text(stringResource(R.string.continue_action))
            }
        }
    }
}

/** On a tablet: the next few books being read, as rows beside the large card. */
@Composable
private fun Beside(books: List<ContinueRow>, actions: ReadActions, modifier: Modifier = Modifier) {
    val colors = KodexTheme.colors
    KodexCard(modifier.fillMaxWidth(), padding = PaddingValues(vertical = 12.dp)) {
        Overline(stringResource(R.string.continue_reading), Modifier.padding(horizontal = 16.dp, vertical = 4.dp))
        books.forEach { book ->
            val fraction = (book.percent / 100).toFloat().coerceIn(0f, 1f)
            Row(
                Modifier.fillMaxWidth().heightIn(min = 72.dp).clickable { actions.read(book.id) }.padding(horizontal = 16.dp, vertical = 8.dp)
                    .testTag("beside-${book.id}"),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                Cover(book.id, width = 44.dp, corner = 6.dp)
                Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                    Text(book.seriesTitle ?: book.title, style = MaterialTheme.typography.titleSmall, color = colors.text, maxLines = 1,
                        overflow = TextOverflow.Ellipsis)
                    Text(
                        listOfNotNull(numberLabel(book.number, "issue", book.libraryType), stringResource(R.string.percent, book.percent.toInt()))
                            .joinToString(" · "),
                        style = MaterialTheme.typography.bodySmall, color = colors.textMuted, maxLines = 1,
                    )
                    ProgressStrip(fraction, track = colors.surface3)
                }
                if (book.downloadState == DownloadState.DONE) {
                    Icon(Icons.Filled.CheckCircle, contentDescription = stringResource(R.string.downloaded), tint = colors.offline,
                        modifier = Modifier.size(18.dp))
                }
                FilledTonalButton(onClick = { actions.read(book.id) }) { Text(stringResource(R.string.read)) }
            }
        }
    }
}

/** Nothing started yet: a word, and the way to the library. */
@Composable
private fun NothingYet(actions: ReadActions) {
    val colors = KodexTheme.colors
    KodexCard(Modifier.fillMaxWidth().testTag("read-nothing")) {
        Text(stringResource(R.string.read_nothing), style = MaterialTheme.typography.bodyLarge, color = colors.textMuted)
        Spacer(Modifier.height(12.dp))
        Button(onClick = actions.toLibrary) { Text(stringResource(R.string.to_library)) }
    }
}
