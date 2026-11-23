package app.kodex.ui.library

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
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
import androidx.compose.ui.draw.clip
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.pluralStringResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextOverflow
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
import app.kodex.ui.SettingsKey
import app.kodex.ui.components.BookCard
import app.kodex.ui.components.BrandBar
import app.kodex.ui.components.Cover
import app.kodex.ui.components.EmptyCatalog
import app.kodex.ui.components.PageHeading
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
    /** Every series, for "Alla serier" under Allt. */
    val allSeries: List<SeriesRow> = emptyList(),
    /** Each library's card covers, by its id. */
    val covers: Map<Int, List<Int>> = emptyMap(),
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
    val account: () -> Unit = {},
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
    val allSeries by vm.allSeries.collectAsStateWithLifecycle(initialValue = emptyList())
    val covers by vm.libraryCovers.collectAsStateWithLifecycle(initialValue = emptyMap())
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
            query, results, seriesResults, allSeries, covers, syncLine(app),
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
            account = { navigator.switchTo(SettingsKey) },
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
                    onAccount = actions.account,
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
                if (state.selected != Shelf.ALL) full("chips") { Shelves(state, actions) }
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

/**
 * Allt (the 2.4 look): the libraries as cards with their covers, the collections, then every
 * series with the filters. What is being read and what came last are under Läs.
 */
@OptIn(ExperimentalLayoutApi::class)
private fun LazyGridScope.everything(state: LibraryHomeState, settings: AppSettings, actions: LibraryHomeActions, wide: Boolean) {
    full("heading") {
        val titles = state.libraries.sumOf { it.bookCount }
        PageHeading(
            stringResource(R.string.tab_library),
            line = listOfNotNull(pluralStringResource(R.plurals.library_titles, titles, titles), state.synced).joinToString(" · "),
        )
    }
    full("search-entry") { SearchEntry(actions) }
    full("libraries-title") { SectionHeader(stringResource(R.string.libraries), count = state.libraries.size) }
    full("libraries") {
        LazyRow(horizontalArrangement = Arrangement.spacedBy(12.dp), modifier = Modifier.testTag("library-cards")) {
            items(state.libraries, key = { it.id }) { library ->
                LibraryCard(library, state.covers[library.id].orEmpty(), wide) { actions.select(library.id) }
            }
            if (state.downloaded.isNotEmpty()) {
                item { DownloadedCard(state.downloaded.size, wide) { actions.select(Shelf.DOWNLOADED) } }
            }
        }
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
    val series = state.allSeries.shown(state.filter, state.sort)
    full("all-series-title") { SectionHeader(stringResource(R.string.all_series), count = series.size) }
    full("all-series-filters") {
        Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
            LazyRow(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.testTag("series-filters")) {
                items(SeriesFilter.entries) { f -> Pill(stringResource(filterLabel(f)), state.filter == f, { actions.filter(f) }) }
            }
            if (state.filtersOpen) {
                LazyRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    items(SeriesSort.entries) { sort -> Pill(stringResource(sortLabel(sort)), state.sort == sort, { actions.sort(sort) }) }
                }
            }
        }
    }
    items(series, key = { "a${it.id}" }) { SeriesCard(it, settings, { actions.openSeries(it.id) }) }
    if (series.isEmpty()) full("all-none") { Quiet(stringResource(R.string.nothing_matches)) }
}

/** A field that opens the search (the search itself has the whole bar). */
@Composable
private fun SearchEntry(actions: LibraryHomeActions) {
    val colors = KodexTheme.colors
    Row(
        Modifier.fillMaxWidth().heightIn(min = 52.dp).clip(CircleShape).background(colors.surface1)
            .border(1.dp, colors.border, CircleShape).clickable { actions.search(true) }.padding(horizontal = 16.dp)
            .testTag("search-entry"),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Icon(Icons.Filled.Search, contentDescription = null, tint = colors.textMuted)
        Text(stringResource(R.string.search_library), style = MaterialTheme.typography.bodyLarge, color = colors.textMuted,
            modifier = Modifier.weight(1f))
        Icon(Icons.Filled.Tune, contentDescription = null, tint = colors.textFaint)
    }
}

/** A library as a card: four of its covers, its name and how much is in it. */
@Composable
private fun LibraryCard(library: LibraryRow, covers: List<Int>, wide: Boolean, onClick: () -> Unit) {
    val colors = KodexTheme.colors
    val width = if (wide) 220.dp else 168.dp
    Column(
        Modifier.width(width).clip(MaterialTheme.shapes.medium).background(colors.surface1)
            .border(1.dp, colors.border, MaterialTheme.shapes.medium).clickable(onClick = onClick).padding(10.dp)
            .testTag("library-card-${library.id}"),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        Mosaic(covers, Modifier.fillMaxWidth())
        Column(Modifier.padding(horizontal = 2.dp)) {
            Text(library.name, style = MaterialTheme.typography.titleMedium, color = colors.text, maxLines = 1, overflow = TextOverflow.Ellipsis)
            Text(stringResource(R.string.library_card_line, library.bookCount, library.seriesCount), style = MaterialTheme.typography.bodySmall,
                color = colors.textMuted, maxLines = 1, overflow = TextOverflow.Ellipsis)
        }
    }
}

/** Up to four covers, two by two (an empty square where there are fewer). */
@Composable
private fun Mosaic(covers: List<Int>, modifier: Modifier = Modifier) {
    val colors = KodexTheme.colors
    Column(modifier, verticalArrangement = Arrangement.spacedBy(4.dp)) {
        (0 until 2).forEach { row ->
            Row(horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                (0 until 2).forEach { col ->
                    val id = covers.getOrNull(row * 2 + col)
                    Box(Modifier.weight(1f)) {
                        if (id != null) {
                            Cover(id, corner = 6.dp)
                        } else {
                            Box(Modifier.fillMaxWidth().aspectRatio(2f / 3f).clip(MaterialTheme.shapes.small).background(colors.surface3))
                        }
                    }
                }
            }
        }
    }
}

/** What is on the device, as a card beside the libraries. */
@Composable
private fun DownloadedCard(count: Int, wide: Boolean, onClick: () -> Unit) {
    val colors = KodexTheme.colors
    val width = if (wide) 220.dp else 168.dp
    Column(
        Modifier.width(width).clip(MaterialTheme.shapes.medium).background(colors.offlineSoft)
            .border(1.dp, colors.border, MaterialTheme.shapes.medium).clickable(onClick = onClick).padding(10.dp)
            .testTag("downloaded-card"),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        Box(Modifier.fillMaxWidth().aspectRatio(2f / 3f).clip(MaterialTheme.shapes.small), contentAlignment = Alignment.Center) {
            Icon(Icons.Filled.DownloadDone, contentDescription = null, tint = colors.offline, modifier = Modifier.size(48.dp))
        }
        Column(Modifier.padding(horizontal = 2.dp)) {
            Text(stringResource(R.string.shelf_downloaded), style = MaterialTheme.typography.titleMedium, color = colors.text, maxLines = 1)
            Text(pluralStringResource(R.plurals.library_titles, count, count), style = MaterialTheme.typography.bodySmall, color = colors.offlineText,
                maxLines = 1)
        }
    }
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
