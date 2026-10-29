package app.kodex.ui.library

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.grid.GridItemSpan
import androidx.compose.foundation.lazy.grid.LazyGridScope
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.DownloadDone
import androidx.compose.material.icons.filled.Search
import androidx.compose.material.icons.filled.Tune
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import app.kodex.R
import app.kodex.data.AppSettings
import app.kodex.data.db.BookRow
import app.kodex.data.db.CollectionEntity
import app.kodex.data.db.ContinueRow
import app.kodex.data.db.LibraryRow
import app.kodex.data.db.SeriesRow
import app.kodex.ui.AppViewModel
import app.kodex.ui.BookKey
import app.kodex.ui.CollectionKey
import app.kodex.ui.Navigator
import app.kodex.ui.SeriesKey
import app.kodex.ui.components.BookCard
import app.kodex.ui.components.BrandBar
import app.kodex.ui.components.ContinueCard
import app.kodex.ui.components.EmptyCatalog
import app.kodex.ui.components.Pill
import app.kodex.ui.components.SectionHeader
import app.kodex.ui.components.SeriesCard
import app.kodex.ui.components.coverCells
import app.kodex.ui.components.syncLine
import app.kodex.ui.theme.KodexTheme
import kotlinx.coroutines.flow.flowOf
import org.koin.compose.viewmodel.koinViewModel

/** The library tab's shelves: everything, what is on the device, or one library (its id). */
object Shelf {
    const val ALL = -1
    const val DOWNLOADED = -2
}

data class LibraryHomeState(
    val libraries: List<LibraryRow> = emptyList(),
    val selected: Int = Shelf.ALL,
    val reading: List<ContinueRow> = emptyList(),
    val recent: List<BookRow> = emptyList(),
    val collections: List<CollectionEntity> = emptyList(),
    val downloaded: List<BookRow> = emptyList(),
    val series: List<SeriesRow> = emptyList(),
    val loose: List<BookRow> = emptyList(),
    val sort: SeriesSort = SeriesSort.TITLE,
    val filter: SeriesFilter = SeriesFilter.ALL,
    val filtersOpen: Boolean = false,
    val searching: Boolean = false,
    val query: String = "",
    val results: List<BookRow> = emptyList(),
    val seriesResults: List<SeriesRow> = emptyList(),
    /** When the catalog was last brought up to date, and what is waiting to be sent. */
    val synced: String? = null,
)

class LibraryHomeActions(
    val select: (Int) -> Unit = {},
    val sort: (SeriesSort) -> Unit = {},
    val filter: (SeriesFilter) -> Unit = {},
    val toggleFilters: () -> Unit = {},
    val search: (Boolean) -> Unit = {},
    val query: (String) -> Unit = {},
    val openBook: (Int) -> Unit = {},
    val openSeries: (Int) -> Unit = {},
    val read: (Int) -> Unit = {},
    val openCollection: (Int, String) -> Unit = { _, _ -> },
)

/** Bibliotek: what is being read, what came last, the collections, and each library's series. */
@Composable
fun LibraryHome(navigator: Navigator, app: AppViewModel) {
    val vm: LibraryViewModel = koinViewModel()
    val settings by app.settings.collectAsStateWithLifecycle()
    val libraries by vm.libraries.collectAsStateWithLifecycle(initialValue = emptyList())
    val reading by vm.continueReading.collectAsStateWithLifecycle(initialValue = emptyList())
    val recent by vm.recentlyAdded.collectAsStateWithLifecycle(initialValue = emptyList())
    val collections by vm.collections.collectAsStateWithLifecycle(initialValue = emptyList())
    val downloaded by vm.downloaded.collectAsStateWithLifecycle(initialValue = emptyList())
    val query by vm.query.collectAsStateWithLifecycle()
    val results by vm.results.collectAsStateWithLifecycle(initialValue = emptyList())
    val seriesResults by vm.seriesResults.collectAsStateWithLifecycle(initialValue = emptyList())
    var selected by rememberSaveable { mutableIntStateOf(Shelf.ALL) }
    var sort by rememberSaveable { mutableStateOf(SeriesSort.TITLE) }
    var filter by rememberSaveable { mutableStateOf(SeriesFilter.ALL) }
    var filtersOpen by rememberSaveable { mutableStateOf(false) }
    var searching by rememberSaveable { mutableStateOf(false) }
    val series by remember(selected) { if (selected >= 0) vm.series(selected) else flowOf(emptyList()) }
        .collectAsStateWithLifecycle(initialValue = emptyList())
    val loose by remember(selected) { if (selected >= 0) vm.looseBooks(selected) else flowOf(emptyList()) }
        .collectAsStateWithLifecycle(initialValue = emptyList())
    BackHandler(enabled = searching || selected != Shelf.ALL) {
        if (searching) {
            searching = false
            vm.query.value = ""
        } else {
            selected = Shelf.ALL
        }
    }
    LibraryHomeContent(
        LibraryHomeState(
            libraries, selected, reading, recent, collections, downloaded, series, loose, sort, filter, filtersOpen, searching,
            query, results, seriesResults, syncLine(app),
        ),
        settings,
        LibraryHomeActions(
            select = { selected = it },
            sort = { sort = it },
            filter = { filter = it },
            toggleFilters = { filtersOpen = !filtersOpen },
            search = { on ->
                searching = on
                if (!on) vm.query.value = ""
            },
            query = { vm.query.value = it },
            openBook = { navigator.open(BookKey(it)) },
            openSeries = { navigator.open(SeriesKey(it)) },
            read = { navigator.read(it) },
            openCollection = { id, name -> navigator.open(CollectionKey(id, name)) },
        ),
        empty = { EmptyCatalog(stringResource(R.string.library_empty), app, it) },
    )
}

@Composable
fun LibraryHomeContent(
    state: LibraryHomeState,
    settings: AppSettings,
    actions: LibraryHomeActions,
    empty: @Composable (Modifier) -> Unit,
) {
    val colors = KodexTheme.colors
    val library = state.libraries.firstOrNull { it.id == state.selected }
    Scaffold(
        topBar = {
            if (state.searching) {
                SearchField(state.query, actions)
            } else {
                BrandBar(
                    subtitle = when (state.selected) {
                        Shelf.ALL -> stringResource(R.string.tab_library)
                        Shelf.DOWNLOADED -> stringResource(R.string.shelf_downloaded)
                        else -> library?.name.orEmpty()
                    },
                    actions = {
                        IconButton(onClick = { actions.search(true) }, modifier = Modifier.testTag("search-open")) {
                            Icon(Icons.Filled.Search, contentDescription = stringResource(R.string.search_library))
                        }
                        if (state.selected >= 0) {
                            IconButton(onClick = actions.toggleFilters, modifier = Modifier.testTag("filters")) {
                                Icon(Icons.Filled.Tune, contentDescription = stringResource(R.string.sort_and_filter),
                                    tint = if (state.filtersOpen) colors.accentText else colors.textMuted)
                            }
                        }
                    },
                )
            }
        },
        containerColor = colors.background,
    ) { padding ->
        if (state.libraries.isEmpty() && !state.searching) {
            empty(Modifier.padding(padding))
            return@Scaffold
        }
        BoxWithConstraints(Modifier.fillMaxSize().padding(padding)) {
            val wide = maxWidth >= 600.dp
            LazyVerticalGrid(
                columns = coverCells(settings.density),
                contentPadding = PaddingValues(start = 16.dp, end = 16.dp, top = 4.dp, bottom = 32.dp),
                horizontalArrangement = Arrangement.spacedBy(12.dp),
                verticalArrangement = Arrangement.spacedBy(16.dp),
                modifier = Modifier.fillMaxSize().testTag("library"),
            ) {
                if (state.searching) {
                    searchResults(state, settings, actions)
                    return@LazyVerticalGrid
                }
                full("chips") { Shelves(state, actions) }
                when (state.selected) {
                    Shelf.ALL -> everything(state, settings, actions, wide)
                    Shelf.DOWNLOADED -> {
                        if (state.downloaded.isEmpty()) full("none") { Quiet(stringResource(R.string.downloads_empty)) }
                        items(state.downloaded, key = { "d${it.id}" }) { BookCard(it, settings, { actions.openBook(it.id) }) }
                    }
                    else -> oneLibrary(state, settings, actions)
                }
            }
        }
    }
}

private fun LazyGridScope.full(key: String, content: @Composable () -> Unit) =
    item(key = key, span = { GridItemSpan(maxLineSpan) }) { content() }

@Composable
private fun Shelves(state: LibraryHomeState, actions: LibraryHomeActions) {
    LazyRow(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxWidth().testTag("shelves")) {
        item { Pill(stringResource(R.string.shelf_all), state.selected == Shelf.ALL, { actions.select(Shelf.ALL) }) }
        items(state.libraries, key = { it.id }) { library ->
            Pill(library.name, state.selected == library.id, { actions.select(library.id) }, Modifier.testTag("library-${library.id}"),
                count = library.bookCount)
        }
        if (state.downloaded.isNotEmpty()) {
            item {
                Pill(stringResource(R.string.shelf_downloaded), state.selected == Shelf.DOWNLOADED, { actions.select(Shelf.DOWNLOADED) },
                    count = state.downloaded.size, icon = Icons.Filled.DownloadDone)
            }
        }
    }
}

@OptIn(ExperimentalLayoutApi::class)
private fun LazyGridScope.everything(state: LibraryHomeState, settings: AppSettings, actions: LibraryHomeActions, wide: Boolean) {
    if (state.reading.isNotEmpty()) {
        full("reading-title") { SectionHeader(stringResource(R.string.continue_reading)) }
        full("reading") {
            LazyRow(horizontalArrangement = Arrangement.spacedBy(14.dp), modifier = Modifier.testTag("home")) {
                items(state.reading, key = { it.id }) { book ->
                    ContinueCard(book, settings, width = if (wide) 200.dp else 160.dp) { actions.read(book.id) }
                }
            }
        }
    }
    if (state.recent.isNotEmpty()) {
        full("recent-title") { SectionHeader(stringResource(R.string.recently_added), mark = KodexTheme.colors.offline) }
        items(state.recent.take(if (wide) 24 else 12), key = { "r${it.id}" }) { BookCard(it, settings, { actions.openBook(it.id) }) }
    }
    if (state.collections.isNotEmpty()) {
        full("collections-title") { SectionHeader(stringResource(R.string.collections)) }
        full("collections") {
            FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                state.collections.forEach { collection ->
                    Pill(collection.name, false, { actions.openCollection(collection.id, collection.name) })
                }
            }
        }
    }
    state.synced?.let { line -> full("synced") { Quiet(line) } }
}

private fun LazyGridScope.oneLibrary(state: LibraryHomeState, settings: AppSettings, actions: LibraryHomeActions) {
    if (state.filtersOpen) {
        full("filters") {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.testTag("filter-row")) {
                LazyRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    items(SeriesSort.entries) { sort -> Pill(stringResource(sortLabel(sort)), state.sort == sort, { actions.sort(sort) }) }
                }
                LazyRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    items(SeriesFilter.entries) { f -> Pill(stringResource(filterLabel(f)), state.filter == f, { actions.filter(f) }) }
                }
            }
        }
    }
    val series = state.series.shown(state.filter, state.sort)
    val loose = state.loose.shownBooks(state.filter, state.sort)
    items(series, key = { "s${it.id}" }) { SeriesCard(it, settings, { actions.openSeries(it.id) }) }
    if (loose.isNotEmpty()) {
        if (series.isNotEmpty()) full("loose-title") { SectionHeader(stringResource(R.string.books_outside_series)) }
        items(loose, key = { "b${it.id}" }) { BookCard(it, settings, { actions.openBook(it.id) }) }
    }
    if (series.isEmpty() && loose.isEmpty()) {
        full("nothing") {
            Quiet(stringResource(if (state.series.isEmpty() && state.loose.isEmpty()) R.string.library_nothing else R.string.nothing_matches))
        }
    }
}

private fun LazyGridScope.searchResults(state: LibraryHomeState, settings: AppSettings, actions: LibraryHomeActions) {
    if (state.query.isBlank()) {
        full("hint") { Quiet(stringResource(R.string.search_hint)) }
        return
    }
    if (state.seriesResults.isNotEmpty()) {
        full("series-title") { SectionHeader(stringResource(R.string.series)) }
        items(state.seriesResults, key = { "s${it.id}" }) { SeriesCard(it, settings, { actions.openSeries(it.id) }) }
    }
    if (state.results.isNotEmpty()) {
        full("books-title") { SectionHeader(stringResource(R.string.books), mark = KodexTheme.colors.offline) }
        items(state.results, key = { "b${it.id}" }) { BookCard(it, settings, { actions.openBook(it.id) }) }
    }
    if (state.results.isEmpty() && state.seriesResults.isEmpty()) full("none") { Quiet(stringResource(R.string.search_nothing, state.query)) }
}

@Composable
private fun SearchField(query: String, actions: LibraryHomeActions) {
    val colors = KodexTheme.colors
    val focus = remember { FocusRequester() }
    LaunchedEffect(Unit) { runCatching { focus.requestFocus() } }
    Row(
        Modifier.fillMaxWidth().statusBarsPadding().padding(horizontal = 8.dp, vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        IconButton(onClick = { actions.search(false) }) {
            Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = stringResource(R.string.back))
        }
        OutlinedTextField(
            value = query,
            onValueChange = actions.query,
            leadingIcon = { Icon(Icons.Filled.Search, contentDescription = null, tint = colors.textMuted) },
            trailingIcon = {
                if (query.isNotEmpty()) {
                    IconButton(onClick = { actions.query("") }) { Icon(Icons.Filled.Close, contentDescription = stringResource(R.string.clear)) }
                }
            },
            placeholder = { Text(stringResource(R.string.search_library)) },
            singleLine = true,
            shape = CircleShape,
            colors = OutlinedTextFieldDefaults.colors(
                unfocusedContainerColor = colors.surface1, focusedContainerColor = colors.surface1,
                unfocusedBorderColor = colors.border, focusedBorderColor = colors.accent,
            ),
            modifier = Modifier.weight(1f).focusRequester(focus).testTag("search"),
        )
    }
}

@Composable
fun Quiet(text: String) {
    Text(
        text,
        style = MaterialTheme.typography.bodyMedium,
        color = KodexTheme.colors.textMuted,
        modifier = Modifier.fillMaxWidth().padding(vertical = 12.dp),
    )
}

fun sortLabel(sort: SeriesSort): Int = when (sort) {
    SeriesSort.TITLE -> R.string.sort_title
    SeriesSort.ADDED -> R.string.sort_added
    SeriesSort.READ -> R.string.sort_read
}

fun filterLabel(filter: SeriesFilter): Int = when (filter) {
    SeriesFilter.ALL -> R.string.filter_all
    SeriesFilter.STARTED -> R.string.filter_started
    SeriesFilter.UNREAD -> R.string.filter_unread
    SeriesFilter.FINISHED -> R.string.filter_finished
    SeriesFilter.FOLLOWING -> R.string.filter_following
    SeriesFilter.DOWNLOADED -> R.string.filter_downloaded
}
