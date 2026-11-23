package app.kodex.ui.search

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.CloudOff
import androidx.compose.material.icons.filled.Search
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
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
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.dp
import androidx.lifecycle.ViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewModelScope
import app.kodex.R
import app.kodex.account.AccountStore
import app.kodex.data.AppSettings
import app.kodex.data.db.BookRow
import app.kodex.data.db.KodexDatabase
import app.kodex.data.db.SeriesRow
import app.kodex.shared.api.FulltextHit
import app.kodex.sync.ApiProvider
import app.kodex.ui.AppViewModel
import app.kodex.ui.BookKey
import app.kodex.ui.LocalSession
import app.kodex.ui.Navigator
import app.kodex.ui.SeriesKey
import app.kodex.ui.components.Cover
import app.kodex.ui.components.Pill
import app.kodex.ui.components.SectionHeader
import app.kodex.ui.components.SeriesCard
import app.kodex.ui.components.StatusChip
import app.kodex.ui.components.bookLine
import app.kodex.ui.components.bookState
import app.kodex.ui.theme.KodexTheme
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.FlowPreview
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.collectLatest
import kotlinx.coroutines.flow.debounce
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.flatMapLatest
import kotlinx.coroutines.flow.flowOf
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.launch
import org.koin.compose.viewmodel.koinViewModel

enum class SearchTab { TITLES, TEXT }

/** What the server answered for a query: its books (in its order) and the places in the text; [failed] when it couldn't be reached. */
data class Remote(
    val query: String = "",
    val bookIds: List<Int>? = null,
    val text: List<FulltextHit> = emptyList(),
    val loading: Boolean = false,
    val failed: Boolean = false,
)

/**
 * Sök: the server's search over titles and metadata and in the books' text, with the catalog on
 * the device when the server can't be reached (titles only).
 */
@OptIn(FlowPreview::class)
class SearchViewModel(db: KodexDatabase, private val accounts: AccountStore, private val apis: ApiProvider) : ViewModel() {
    private val catalog = db.catalog()
    val query = MutableStateFlow("")
    val remote = MutableStateFlow(Remote())

    @OptIn(ExperimentalCoroutinesApi::class)
    val series: Flow<List<SeriesRow>> = query.flatMapLatest { text ->
        if (text.isBlank()) flowOf(emptyList()) else catalog.searchSeries(text.trim())
    }

    @OptIn(ExperimentalCoroutinesApi::class)
    val localBooks: Flow<List<BookRow>> = query.flatMapLatest { text ->
        if (text.isBlank()) flowOf(emptyList()) else catalog.searchBooks(text.trim())
    }

    /** The server's books as the catalog on the device has them (with progress and downloads), in the server's order. */
    @OptIn(ExperimentalCoroutinesApi::class)
    val serverBooks: Flow<List<BookRow>?> = remote.flatMapLatest { r ->
        val ids = r.bookIds ?: return@flatMapLatest flowOf(null)
        if (ids.isEmpty()) flowOf(emptyList()) else catalog.booksByIds(ids).map { rows -> rows.associateBy { it.id }.let { byId -> ids.mapNotNull { byId[it] } } }
    }

    /** The books the text hits are in, for their covers and formats. */
    @OptIn(ExperimentalCoroutinesApi::class)
    val textBooks: Flow<List<BookRow>> = remote.flatMapLatest { r ->
        val ids = r.text.map { it.bookId }.distinct()
        if (ids.isEmpty()) flowOf(emptyList()) else catalog.booksByIds(ids)
    }

    init {
        viewModelScope.launch {
            query.debounce(350).map { it.trim() }.distinctUntilChanged().collectLatest { search(it) }
        }
    }

    private suspend fun search(text: String) {
        if (text.length < 2) {
            remote.value = Remote(query = text)
            return
        }
        remote.value = remote.value.copy(loading = true)
        val session = accounts.current()
        if (session == null) {
            remote.value = Remote(query = text, failed = true)
            return
        }
        val api = apis.api(session)
        remote.value = try {
            val books = api.searchBooks(text)
            val hits = try {
                api.searchFulltext(text)
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                emptyList()
            }
            Remote(query = text, bookIds = books.map { it.bookId }, text = hits)
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            Remote(query = text, failed = true)
        }
    }
}

/** A place in a book's text, with the book as the device has it (when it does). */
data class TextHitRow(val hit: FulltextHit, val book: BookRow?)

data class SearchUi(
    val query: String = "",
    val tab: SearchTab = SearchTab.TITLES,
    val series: List<SeriesRow> = emptyList(),
    val books: List<BookRow> = emptyList(),
    val text: List<TextHitRow> = emptyList(),
    /** The server answered (else the catalog on the device was searched). */
    val online: Boolean = false,
    val failed: Boolean = false,
    val loading: Boolean = false,
    /** The server's name, for "Söker på …". */
    val server: String? = null,
)

class SearchActions(
    val back: () -> Unit = {},
    val query: (String) -> Unit = {},
    val tab: (SearchTab) -> Unit = {},
    val openSeries: (Int) -> Unit = {},
    val openBook: (Int) -> Unit = {},
    val read: (Int, String?, String?) -> Unit = { _, _, _ -> },
)

@Composable
fun SearchScreen(navigator: Navigator, app: AppViewModel) {
    val vm: SearchViewModel = koinViewModel()
    val settings by app.settings.collectAsStateWithLifecycle()
    val query by vm.query.collectAsStateWithLifecycle()
    val remote by vm.remote.collectAsStateWithLifecycle()
    val series by vm.series.collectAsStateWithLifecycle(initialValue = emptyList())
    val local by vm.localBooks.collectAsStateWithLifecycle(initialValue = emptyList())
    val server by vm.serverBooks.collectAsStateWithLifecycle(initialValue = null)
    val textBooks by vm.textBooks.collectAsStateWithLifecycle(initialValue = emptyList())
    var tab by rememberSaveable { mutableStateOf(SearchTab.TITLES) }
    val session = LocalSession.current
    val online = remote.bookIds != null && remote.query == query.trim()
    SearchContent(
        SearchUi(
            query = query,
            tab = tab,
            series = series,
            books = if (online) server ?: local else local,
            text = if (online) remote.text.map { hit -> TextHitRow(hit, textBooks.firstOrNull { it.id == hit.bookId }) } else emptyList(),
            online = online,
            failed = remote.failed,
            loading = remote.loading,
            server = session?.server?.let { runCatching { java.net.URI(it).host }.getOrNull() ?: it },
        ),
        settings,
        SearchActions(
            back = navigator::back,
            query = { vm.query.value = it },
            tab = { tab = it },
            openSeries = { navigator.open(SeriesKey(it)) },
            openBook = { navigator.open(BookKey(it)) },
            read = { id, position, kind -> navigator.read(id, position, kind) },
        ),
    )
}

@Composable
fun SearchContent(state: SearchUi, settings: AppSettings, actions: SearchActions, focus: Boolean = true) {
    val colors = KodexTheme.colors
    Scaffold(topBar = { SearchBar(state.query, actions, focus) }, containerColor = colors.background) { padding ->
        Column(Modifier.fillMaxSize().padding(padding)) {
            if (state.loading) LinearProgressIndicator(Modifier.fillMaxWidth().testTag("search-loading"))
            Row(
                Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 8.dp),
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                Pill(stringResource(R.string.search_titles), state.tab == SearchTab.TITLES, { actions.tab(SearchTab.TITLES) },
                    Modifier.testTag("search-tab-titles"), count = if (state.query.isBlank()) null else state.series.size + state.books.size)
                Pill(stringResource(R.string.search_text), state.tab == SearchTab.TEXT, { actions.tab(SearchTab.TEXT) },
                    Modifier.testTag("search-tab-text"), count = if (state.online) state.text.size else null)
            }
            if (state.query.isNotBlank()) {
                Row(Modifier.padding(horizontal = 16.dp, vertical = 2.dp)) {
                    when {
                        state.online && state.server != null -> StatusChip(stringResource(R.string.search_server, state.server))
                        state.failed -> StatusChip(stringResource(R.string.search_offline), dot = colors.textFaint, icon = Icons.Filled.CloudOff)
                    }
                }
            }
            LazyColumn(
                contentPadding = PaddingValues(start = 16.dp, end = 16.dp, top = 8.dp, bottom = 32.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp),
                modifier = Modifier.fillMaxSize().testTag("search-results"),
            ) {
                if (state.query.isBlank()) {
                    item("hint") { Quiet(stringResource(R.string.search_hint)) }
                    return@LazyColumn
                }
                when (state.tab) {
                    SearchTab.TITLES -> {
                        if (state.series.isNotEmpty()) {
                            item("series-title") { SectionHeader(stringResource(R.string.series), count = state.series.size) }
                            item("series") {
                                LazyRow(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                                    items(state.series, key = { "s${it.id}" }) { SeriesCard(it, settings, { actions.openSeries(it.id) }, width = 120.dp) }
                                }
                            }
                        }
                        if (state.books.isNotEmpty()) {
                            item("books-title") { SectionHeader(stringResource(R.string.books), count = state.books.size) }
                            items(state.books, key = { "b${it.id}" }) { book -> BookHit(book, state.query, actions) }
                        }
                        if (state.series.isEmpty() && state.books.isEmpty() && !state.loading) {
                            item("none") { Quiet(stringResource(R.string.search_nothing, state.query)) }
                        }
                    }
                    SearchTab.TEXT -> {
                        when {
                            !state.online -> item("offline") { Quiet(stringResource(if (state.failed) R.string.search_text_offline else R.string.search_text_hint)) }
                            state.text.isEmpty() && !state.loading -> {
                                item("none") { Quiet(stringResource(R.string.search_nothing, state.query)) }
                                item("text-hint") { Quiet(stringResource(R.string.search_text_hint)) }
                            }
                            else -> items(state.text, key = { "${it.hit.bookId}:${it.hit.position}" }) { row -> TextHit(row, actions) }
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun SearchBar(query: String, actions: SearchActions, focus: Boolean) {
    val colors = KodexTheme.colors
    val requester = remember { FocusRequester() }
    LaunchedEffect(Unit) { if (focus) runCatching { requester.requestFocus() } }
    Row(
        Modifier.fillMaxWidth().statusBarsPadding().padding(horizontal = 8.dp, vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        IconButton(onClick = actions.back) { Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = stringResource(R.string.back)) }
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
            modifier = Modifier.weight(1f).focusRequester(requester).testTag("search"),
        )
    }
}

/** A book found: its cover, its title with the words marked, its line, and "Läs". */
@Composable
private fun BookHit(book: BookRow, query: String, actions: SearchActions) {
    val colors = KodexTheme.colors
    Row(
        Modifier.fillMaxWidth().heightIn(min = 76.dp).clip(MaterialTheme.shapes.medium).background(colors.surface1)
            .clickable { actions.openBook(book.id) }.padding(10.dp).testTag("search-book-${book.id}"),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Cover(book.id, width = 44.dp, corner = 6.dp)
        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(2.dp)) {
            Text(marked(book.title, query, SpanStyle(color = colors.accentText, fontWeight = FontWeight.Bold)), style = MaterialTheme.typography.titleSmall,
                color = colors.text, maxLines = 2, overflow = TextOverflow.Ellipsis)
            bookLine(book)?.let { Text(it, style = MaterialTheme.typography.bodySmall, color = colors.textMuted, maxLines = 1, overflow = TextOverflow.Ellipsis) }
            Text(bookState(book), style = MaterialTheme.typography.bodySmall, color = colors.textFaint, maxLines = 1, overflow = TextOverflow.Ellipsis)
        }
        FilledTonalButton(onClick = { actions.read(book.id, null, null) }) { Text(stringResource(R.string.read)) }
    }
}

/** A place in a book's text: the book, the words around the hit, a tap opens it there. */
@Composable
private fun TextHit(row: TextHitRow, actions: SearchActions) {
    val colors = KodexTheme.colors
    val at = textPosition(row.book?.format, row.hit.position)
    Row(
        Modifier.fillMaxWidth().clip(MaterialTheme.shapes.medium).background(colors.surface1)
            .clickable { actions.read(row.hit.bookId, at?.first, at?.second) }.padding(10.dp).testTag("search-text-${row.hit.bookId}"),
        horizontalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Cover(row.hit.bookId, width = 44.dp, corner = 6.dp)
        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Text(row.book?.title ?: row.hit.title, style = MaterialTheme.typography.titleSmall, color = colors.text, maxLines = 1,
                overflow = TextOverflow.Ellipsis)
            Text(snippet(row.hit.snippet, SpanStyle(color = colors.accentText, fontWeight = FontWeight.Bold, background = colors.accentSoft)),
                style = MaterialTheme.typography.bodyMedium, color = colors.textMuted, maxLines = 4, overflow = TextOverflow.Ellipsis)
        }
    }
}

@Composable
private fun Quiet(text: String) {
    Text(text, style = MaterialTheme.typography.bodyMedium, color = KodexTheme.colors.textMuted, modifier = Modifier.fillMaxWidth().padding(vertical = 12.dp))
}

/** Where a text hit opens the reader: a chapter's path in an EPUB (as the app's own locator), a page in a PDF. */
fun textPosition(format: String?, position: String): Pair<String, String>? = when (format?.lowercase()) {
    "epub" -> "readium:$position@0.00000" to "other"
    "pdf" -> position to "pdf"
    else -> null
}

/** The server's snippet (escaped HTML, the hit in `<mark>`) as text with the hits in [mark]. */
fun snippet(html: String, mark: SpanStyle): AnnotatedString = buildAnnotatedString {
    var rest = html
    while (rest.isNotEmpty()) {
        val start = rest.indexOf("<mark>")
        if (start < 0) {
            append(unescape(rest))
            break
        }
        append(unescape(rest.substring(0, start)))
        val end = rest.indexOf("</mark>", start)
        if (end < 0) {
            append(unescape(rest.substring(start + 6)))
            break
        }
        withStyle(mark) { append(unescape(rest.substring(start + 6, end))) }
        rest = rest.substring(end + 7)
    }
}

private fun unescape(text: String): String =
    text.replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", "\"").replace("&#x27;", "'").replace("&#39;", "'").replace("&amp;", "&")

/** [text] with each place [query] is in it (ignoring case) in [mark]. */
fun marked(text: String, query: String, mark: SpanStyle): AnnotatedString = buildAnnotatedString {
    val needle = query.trim()
    if (needle.isEmpty()) {
        append(text)
        return@buildAnnotatedString
    }
    var from = 0
    while (true) {
        val at = text.indexOf(needle, from, ignoreCase = true)
        if (at < 0) {
            append(text.substring(from))
            break
        }
        append(text.substring(from, at))
        withStyle(mark) { append(text.substring(at, at + needle.length)) }
        from = at + needle.length
    }
}
