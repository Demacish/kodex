package app.kodex.ui.discover

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.MenuBook
import androidx.compose.material.icons.filled.AutoAwesome
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Favorite
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.VisibilityOff
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.ViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewModelScope
import app.kodex.R
import app.kodex.account.AccountStore
import app.kodex.data.AppSettings
import app.kodex.data.db.KodexDatabase
import app.kodex.data.db.SeriesRow
import app.kodex.shared.api.KodexApiException
import app.kodex.shared.api.Recommendation
import app.kodex.shared.api.ReleaseEvent
import app.kodex.sync.ApiProvider
import app.kodex.ui.AppViewModel
import app.kodex.ui.BookKey
import app.kodex.ui.Navigator
import app.kodex.ui.SeriesKey
import app.kodex.ui.components.BrandBar
import app.kodex.ui.components.Cover
import app.kodex.ui.components.KodexCard
import app.kodex.ui.components.MediaBadge
import app.kodex.ui.components.SectionHeader
import app.kodex.ui.components.SeriesCard
import app.kodex.ui.components.mediaKind
import app.kodex.ui.components.readable
import app.kodex.ui.components.rtl
import app.kodex.ui.theme.KodexTheme
import coil3.compose.AsyncImage
import java.time.LocalDate
import java.time.format.DateTimeFormatter
import java.time.format.FormatStyle
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import org.koin.compose.viewmodel.koinViewModel

/** What the server says (it needs the network): new numbers in the followed series, and suggestions. */
data class DiscoverRemote(
    val loading: Boolean = false,
    val releases: List<ReleaseEvent>? = null,
    val recommendations: List<Recommendation>? = null,
    /** Why the server couldn't be asked (a string resource). */
    val problem: Int? = null,
    /** The server's own word on suggestions (no AI set up, for one). */
    val suggestionProblem: String? = null,
    val generating: Boolean = false,
    /** Something done that is worth saying (a request made). */
    val note: Int? = null,
)

class DiscoverViewModel(db: KodexDatabase, private val accounts: AccountStore, private val apis: ApiProvider) : ViewModel() {
    val followed = db.catalog().followedSeries()
    val remote = MutableStateFlow(DiscoverRemote())

    fun refresh() = viewModelScope.launch {
        val session = accounts.current() ?: return@launch
        val api = apis.api(session)
        remote.update { it.copy(loading = true, problem = null) }
        val releases = try {
            api.releases()
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            remote.update { it.copy(loading = false, problem = R.string.discover_unreachable) }
            return@launch
        }
        val suggestions = try {
            api.recommendations()
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            null
        }
        remote.update { it.copy(loading = false, releases = releases, recommendations = suggestions ?: it.recommendations) }
    }

    fun dismiss(event: ReleaseEvent) = act {
        it.dismissRelease(event.id)
        remote.update { state -> state.copy(releases = state.releases?.filterNot { r -> r.id == event.id }) }
    }

    fun swipe(item: Recommendation, want: Boolean) = act {
        it.swipe(item.id, want)
        remote.update { state ->
            state.copy(recommendations = state.recommendations?.filterNot { r -> r.id == item.id }, note = if (want) R.string.discover_requested else null)
        }
    }

    fun generate() = viewModelScope.launch {
        val session = accounts.current() ?: return@launch
        remote.update { it.copy(generating = true, suggestionProblem = null) }
        try {
            val fresh = apis.api(session).generateRecommendations()
            remote.update { it.copy(generating = false, recommendations = fresh) }
        } catch (e: CancellationException) {
            throw e
        } catch (e: KodexApiException) {
            remote.update { it.copy(generating = false, suggestionProblem = e.message) }
        } catch (e: Exception) {
            remote.update { it.copy(generating = false, problem = R.string.discover_unreachable) }
        }
    }

    private fun act(block: suspend (app.kodex.shared.api.KodexApi) -> Unit) = viewModelScope.launch {
        val session = accounts.current() ?: return@launch
        try {
            block(apis.api(session))
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            remote.update { it.copy(problem = R.string.discover_unreachable) }
        }
    }
}

class DiscoverActions(
    val refresh: () -> Unit = {},
    val openSeries: (Int) -> Unit = {},
    val openBook: (Int) -> Unit = {},
    val dismiss: (ReleaseEvent) -> Unit = {},
    val swipe: (Recommendation, Boolean) -> Unit = { _, _ -> },
    val generate: () -> Unit = {},
)

/** Upptäck: the followed series and their new numbers, what is coming, and the server's suggestions. */
@Composable
fun DiscoverScreen(navigator: Navigator, app: AppViewModel) {
    val vm: DiscoverViewModel = koinViewModel()
    val settings by app.settings.collectAsStateWithLifecycle()
    val followed by vm.followed.collectAsStateWithLifecycle(initialValue = emptyList())
    val remote by vm.remote.collectAsStateWithLifecycle()
    LaunchedEffect(Unit) { if (remote.releases == null) vm.refresh() }
    DiscoverContent(
        followed, remote, settings,
        DiscoverActions(
            refresh = { vm.refresh() },
            openSeries = { navigator.open(SeriesKey(it)) },
            openBook = { navigator.open(BookKey(it)) },
            dismiss = { vm.dismiss(it) },
            swipe = { item, want -> vm.swipe(item, want) },
            generate = { vm.generate() },
        ),
    )
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun DiscoverContent(followed: List<SeriesRow>, remote: DiscoverRemote, settings: AppSettings, actions: DiscoverActions) {
    val colors = KodexTheme.colors
    val byId = followed.associateBy { it.id }
    Scaffold(
        topBar = {
            BrandBar(stringResource(R.string.tab_discover)) {
                IconButton(onClick = actions.refresh, modifier = Modifier.testTag("discover-refresh")) {
                    Icon(Icons.Filled.Refresh, contentDescription = stringResource(R.string.refresh))
                }
            }
        },
        containerColor = colors.background,
    ) { padding ->
        PullToRefreshBox(isRefreshing = remote.loading, onRefresh = actions.refresh, modifier = Modifier.fillMaxSize().padding(padding)) {
            BoxWithConstraints(Modifier.fillMaxSize(), contentAlignment = Alignment.TopCenter) {
                val wide = maxWidth >= 600.dp
                val released = remote.releases.orEmpty().filter { it.status != "unreleased" }
                val coming = remote.releases.orEmpty().filter { it.status == "unreleased" }
                LazyColumn(
                    Modifier.readable(900.dp).fillMaxSize().testTag("discover"),
                    contentPadding = PaddingValues(start = 16.dp, end = 16.dp, top = 4.dp, bottom = 32.dp),
                    verticalArrangement = Arrangement.spacedBy(12.dp),
                ) {
                    remote.problem?.let { problem -> item(key = "problem") { Note(stringResource(problem), colors.danger) } }
                    remote.note?.let { note -> item(key = "note") { Note(stringResource(note), colors.offlineText) } }

                    item(key = "new-title") {
                        SectionHeader(stringResource(R.string.discover_new), mark = colors.offline) {
                            if (released.isNotEmpty()) {
                                Text(
                                    stringResource(R.string.discover_new_count, released.size).uppercase(),
                                    style = MaterialTheme.typography.labelSmall,
                                    color = colors.offlineText,
                                    modifier = Modifier.clip(CircleShape).background(colors.offlineSoft).padding(horizontal = 8.dp, vertical = 3.dp),
                                )
                            }
                        }
                    }
                    when {
                        remote.releases == null && remote.loading -> item(key = "loading") { Loading() }
                        remote.releases == null -> item(key = "offline") { Quiet(stringResource(R.string.discover_needs_server)) }
                        released.isEmpty() -> item(key = "no-new") {
                            Quiet(stringResource(if (followed.isEmpty()) R.string.discover_follow_hint else R.string.discover_nothing_new))
                        }
                        else -> items(released, key = { "r${it.id}" }) { event ->
                            ReleaseCard(event, byId[event.seriesId], settings, actions)
                        }
                    }

                    if (followed.isNotEmpty()) {
                        item(key = "followed-title") { SectionHeader(stringResource(R.string.discover_following, followed.size)) }
                        item(key = "followed") {
                            LazyRow(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                                items(followed, key = { it.id }) { series ->
                                    SeriesCard(series, settings, { actions.openSeries(series.id) }, width = if (wide) 136.dp else 112.dp)
                                }
                            }
                        }
                    }

                    if (coming.isNotEmpty()) {
                        item(key = "coming-title") { SectionHeader(stringResource(R.string.discover_coming)) }
                        item(key = "coming") { Coming(coming, actions) }
                    }

                    item(key = "suggest-title") {
                        SectionHeader(stringResource(R.string.discover_suggestions), mark = colors.accentText)
                    }
                    val suggestions = remote.recommendations.orEmpty()
                    if (suggestions.isEmpty()) {
                        item(key = "suggest-empty") { NoSuggestions(remote, actions) }
                    } else {
                        items(suggestions, key = { "s${it.id}" }) { Suggestion(it, actions) }
                    }
                }
            }
        }
    }
}

@Composable
private fun Note(text: String, color: androidx.compose.ui.graphics.Color) {
    Text(text, style = MaterialTheme.typography.bodyMedium, color = color, modifier = Modifier.padding(vertical = 4.dp))
}

@Composable
private fun Quiet(text: String) {
    Text(text, style = MaterialTheme.typography.bodyMedium, color = KodexTheme.colors.textMuted, modifier = Modifier.padding(vertical = 8.dp))
}

@Composable
private fun Loading() {
    Box(Modifier.fillMaxWidth().height(96.dp), contentAlignment = Alignment.Center) { CircularProgressIndicator() }
}

/** "#45", or the title when the number isn't known. */
private fun ReleaseEvent.label(): String = listOfNotNull(issueNumber?.let { "#$it" }, title).joinToString(" · ")

private fun date(iso: String?): String? =
    iso?.let { runCatching { LocalDate.parse(it).format(DateTimeFormatter.ofLocalizedDate(FormatStyle.MEDIUM)) }.getOrNull() }

/** A new number in a followed series: in the library already (open it), or out but not here. */
@Composable
private fun ReleaseCard(event: ReleaseEvent, series: SeriesRow?, settings: AppSettings, actions: DiscoverActions) {
    val colors = KodexTheme.colors
    val owned = event.status == "owned" && event.ownedBookId != null
    Surface(
        shape = MaterialTheme.shapes.medium,
        color = colors.surface1,
        border = BorderStroke(1.dp, colors.border),
        modifier = Modifier.fillMaxWidth().clickable {
            val book = event.ownedBookId
            if (owned && book != null) actions.openBook(book) else actions.openSeries(event.seriesId)
        }.testTag("release-${event.id}"),
    ) {
        Row(Modifier.padding(12.dp), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(14.dp)) {
            Cover(event.ownedBookId ?: series?.firstBookId, width = 56.dp, corner = 6.dp)
            Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(3.dp)) {
                series?.let { MediaBadge(mediaKind(it.libraryType, ""), stringResource(R.string.badge_series), settings.rtl(it.libraryType)) }
                Text(event.seriesTitle, style = MaterialTheme.typography.titleMedium, color = colors.text, maxLines = 1, overflow = TextOverflow.Ellipsis)
                Text(
                    stringResource(if (owned) R.string.release_owned else R.string.release_out, event.label()),
                    style = MaterialTheme.typography.bodyMedium,
                    color = if (owned) colors.offlineText else colors.accentText,
                    maxLines = 1, overflow = TextOverflow.Ellipsis,
                )
                date(event.storeDate)?.let { Text(it, style = MaterialTheme.typography.bodySmall, color = colors.textMuted) }
            }
            if (owned) {
                Box(Modifier.size(44.dp).clip(CircleShape).background(colors.offlineSoft), contentAlignment = Alignment.Center) {
                    Icon(Icons.AutoMirrored.Filled.MenuBook, contentDescription = stringResource(R.string.open), tint = colors.offlineText)
                }
            } else {
                IconButton(onClick = { actions.dismiss(event) }) {
                    Icon(Icons.Filled.VisibilityOff, contentDescription = stringResource(R.string.release_hide), tint = colors.textMuted)
                }
            }
        }
    }
}

/** What is coming, by date. */
@Composable
private fun Coming(events: List<ReleaseEvent>, actions: DiscoverActions) {
    val colors = KodexTheme.colors
    KodexCard(Modifier.fillMaxWidth(), padding = PaddingValues(vertical = 4.dp)) {
        events.forEach { event ->
            Row(
                Modifier.fillMaxWidth().clickable { actions.openSeries(event.seriesId) }.padding(start = 16.dp, end = 4.dp, top = 6.dp, bottom = 6.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(
                    date(event.storeDate) ?: stringResource(R.string.release_no_date),
                    style = MaterialTheme.typography.labelMedium,
                    color = colors.accentText,
                    modifier = Modifier.width(96.dp),
                )
                Column(Modifier.weight(1f)) {
                    Text(event.seriesTitle, style = MaterialTheme.typography.titleSmall, color = colors.text, maxLines = 1, overflow = TextOverflow.Ellipsis)
                    Text(event.label(), style = MaterialTheme.typography.bodySmall, color = colors.textMuted, maxLines = 1, overflow = TextOverflow.Ellipsis)
                }
                IconButton(onClick = { actions.dismiss(event) }) {
                    Icon(Icons.Filled.VisibilityOff, contentDescription = stringResource(R.string.release_hide), tint = colors.textMuted)
                }
            }
        }
    }
}

/** A suggestion: want it (a request on the server) or not. */
@Composable
private fun Suggestion(item: Recommendation, actions: DiscoverActions) {
    val colors = KodexTheme.colors
    KodexCard(Modifier.fillMaxWidth().testTag("suggestion-${item.id}")) {
        Row(horizontalArrangement = Arrangement.spacedBy(14.dp)) {
            Box(Modifier.width(72.dp).aspectRatio(2f / 3f).clip(RoundedCornerShape(8.dp)).background(colors.surface3)) {
                item.coverUrl?.let { AsyncImage(it, contentDescription = null, contentScale = ContentScale.Crop, modifier = Modifier.fillMaxSize()) }
            }
            Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                Text(item.title, style = MaterialTheme.typography.titleMedium, color = colors.text)
                item.author?.let { Text(it, style = MaterialTheme.typography.bodyMedium, color = colors.accentText) }
                item.reason?.let { Text(it, style = MaterialTheme.typography.bodySmall, color = colors.textMuted, maxLines = 4, overflow = TextOverflow.Ellipsis) }
            }
        }
        Spacer(Modifier.height(12.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Button(onClick = { actions.swipe(item, true) }, modifier = Modifier.weight(1f).heightIn(min = 48.dp), shape = MaterialTheme.shapes.small) {
                Icon(Icons.Filled.Favorite, contentDescription = null)
                Spacer(Modifier.width(8.dp))
                Text(stringResource(R.string.discover_want))
            }
            OutlinedButton(
                onClick = { actions.swipe(item, false) },
                modifier = Modifier.weight(1f).heightIn(min = 48.dp),
                shape = MaterialTheme.shapes.small,
                border = BorderStroke(1.dp, colors.border),
                colors = ButtonDefaults.outlinedButtonColors(containerColor = colors.surface1, contentColor = colors.text),
            ) {
                Icon(Icons.Filled.Close, contentDescription = null)
                Spacer(Modifier.width(8.dp))
                Text(stringResource(R.string.discover_skip))
            }
        }
    }
}

@Composable
private fun NoSuggestions(remote: DiscoverRemote, actions: DiscoverActions) {
    val colors = KodexTheme.colors
    KodexCard(Modifier.fillMaxWidth()) {
        Text(stringResource(R.string.discover_suggestions_empty), style = MaterialTheme.typography.bodyMedium, color = colors.textMuted)
        remote.suggestionProblem?.let {
            Spacer(Modifier.height(6.dp))
            Text(it, style = MaterialTheme.typography.bodySmall, color = colors.danger)
        }
        Spacer(Modifier.height(12.dp))
        Button(onClick = actions.generate, enabled = !remote.generating && remote.releases != null, shape = MaterialTheme.shapes.small,
            modifier = Modifier.testTag("generate")) {
            if (remote.generating) {
                CircularProgressIndicator(Modifier.size(18.dp), strokeWidth = 2.dp, color = colors.onAccent)
            } else {
                Icon(Icons.Filled.AutoAwesome, contentDescription = null)
            }
            Spacer(Modifier.width(8.dp))
            Text(stringResource(R.string.discover_generate))
        }
    }
}
