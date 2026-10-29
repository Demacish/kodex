package app.kodex.ui.downloads

import android.content.Context
import android.net.ConnectivityManager
import android.net.Network
import android.net.NetworkCapabilities
import android.os.SystemClock
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.detectDragGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
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
import androidx.compose.material.icons.filled.ArrowDownward
import androidx.compose.material.icons.filled.CleaningServices
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.CloudOff
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.DragIndicator
import androidx.compose.material.icons.filled.Pause
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.SdStorage
import androidx.compose.material.icons.filled.VerticalAlignTop
import androidx.compose.material.icons.filled.Wifi
import androidx.compose.material.icons.filled.WifiOff
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.pluralStringResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.zIndex
import androidx.lifecycle.ViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewModelScope
import app.kodex.R
import app.kodex.data.AppSettings
import app.kodex.data.db.DownloadRow
import app.kodex.data.db.DownloadState
import app.kodex.data.db.KodexDatabase
import app.kodex.download.Downloads
import app.kodex.ui.AppViewModel
import app.kodex.ui.BookKey
import app.kodex.ui.Navigator
import app.kodex.ui.components.BrandBar
import app.kodex.ui.components.Cover
import app.kodex.ui.components.KodexCard
import app.kodex.ui.components.MediaBadge
import app.kodex.ui.components.Pill
import app.kodex.ui.components.SectionHeader
import app.kodex.ui.components.mediaKind
import app.kodex.ui.components.numberLabel
import app.kodex.ui.components.readable
import app.kodex.ui.components.rtl
import app.kodex.ui.components.size
import app.kodex.ui.theme.KodexTheme
import java.text.DateFormat
import java.util.Date
import kotlinx.coroutines.channels.awaitClose
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.callbackFlow
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.launch
import org.koin.compose.viewmodel.koinViewModel

/** A download with how fast it comes (bytes a second; 0 when it isn't running). */
data class Transfer(val row: DownloadRow, val rate: Double = 0.0)

/** The network as downloads see it. */
data class NetworkState(val connected: Boolean = true, val unmetered: Boolean = true)

enum class DownloadsTab { ACTIVE, QUEUE, HISTORY }

/** The downloads with their speeds, and what can be done with them. */
class DownloadsViewModel(context: Context, db: KodexDatabase, private val downloads: Downloads) : ViewModel() {
    private val seen = mutableMapOf<Int, Pair<Long, Long>>()
    private val rates = mutableMapOf<Int, Double>()

    val transfers: Flow<List<Transfer>> = db.downloads().list().map { rows ->
        val now = SystemClock.elapsedRealtime()
        rows.map { row ->
            if (row.state == DownloadState.RUNNING) {
                val (bytes, at) = seen[row.bookId] ?: (row.bytes to now)
                if (now > at && row.bytes >= bytes) {
                    val instant = (row.bytes - bytes) * 1000.0 / (now - at)
                    rates[row.bookId] = rates[row.bookId]?.let { it * 0.7 + instant * 0.3 } ?: instant
                }
                seen[row.bookId] = row.bytes to now
            } else {
                seen.remove(row.bookId)
                rates.remove(row.bookId)
            }
            Transfer(row, rates[row.bookId] ?: 0.0)
        }
    }

    val network: Flow<NetworkState> = networkState(context.applicationContext)

    fun pause(id: Int) = viewModelScope.launch { downloads.pause(id) }

    fun resume(id: Int) = viewModelScope.launch { downloads.resume(id) }

    fun remove(id: Int) = viewModelScope.launch { downloads.remove(id) }

    fun pauseAll() = viewModelScope.launch { downloads.pauseAll() }

    fun resumeAll() = viewModelScope.launch { downloads.resumeAll() }

    fun moveToFront(id: Int) = viewModelScope.launch { downloads.moveToFront(id) }

    fun reorder(ids: List<Int>) = viewModelScope.launch { downloads.reorder(ids) }
}

private fun networkState(context: Context): Flow<NetworkState> = callbackFlow {
    val manager = context.getSystemService(ConnectivityManager::class.java)
    fun current(): NetworkState {
        val caps = manager.getNetworkCapabilities(manager.activeNetwork)
        return NetworkState(
            connected = caps?.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET) == true,
            unmetered = caps?.hasCapability(NetworkCapabilities.NET_CAPABILITY_NOT_METERED) == true,
        )
    }
    trySend(current())
    val callback = object : ConnectivityManager.NetworkCallback() {
        override fun onAvailable(network: Network) {
            trySend(current())
        }

        override fun onCapabilitiesChanged(network: Network, capabilities: NetworkCapabilities) {
            trySend(current())
        }

        override fun onLost(network: Network) {
            trySend(current())
        }
    }
    manager.registerDefaultNetworkCallback(callback)
    awaitClose { manager.unregisterNetworkCallback(callback) }
}.distinctUntilChanged()

class DownloadsActions(
    val tab: (DownloadsTab) -> Unit = {},
    val open: (Int) -> Unit = {},
    val pause: (Int) -> Unit = {},
    val resume: (Int) -> Unit = {},
    val remove: (Int) -> Unit = {},
    val pauseAll: () -> Unit = {},
    val resumeAll: () -> Unit = {},
    val moveToFront: (Int) -> Unit = {},
    val reorder: (List<Int>) -> Unit = {},
    val cleanup: (Int) -> Unit = {},
)

/** Nedladdat: what is on its way and how fast, the queue, what came, and how much room is left. */
@Composable
fun DownloadsScreen(app: AppViewModel, navigator: Navigator) {
    val vm: DownloadsViewModel = koinViewModel()
    val settings by app.settings.collectAsStateWithLifecycle()
    val transfers by vm.transfers.collectAsStateWithLifecycle(initialValue = emptyList())
    val network by vm.network.collectAsStateWithLifecycle(initialValue = NetworkState())
    val used by app.usedBytes.collectAsStateWithLifecycle(initialValue = 0L)
    var tab by rememberSaveable { mutableStateOf<DownloadsTab?>(null) }
    val free = remember(transfers.size, settings.storage) { app.freeBytes(settings.storage) }
    DownloadsContent(
        transfers, network, free, used, settings,
        tab ?: if (transfers.any { it.row.state.active() }) DownloadsTab.ACTIVE else DownloadsTab.HISTORY,
        DownloadsActions(
            tab = { tab = it },
            open = { navigator.open(BookKey(it)) },
            pause = { vm.pause(it) },
            resume = { vm.resume(it) },
            remove = { vm.remove(it) },
            pauseAll = { vm.pauseAll() },
            resumeAll = { vm.resumeAll() },
            moveToFront = { vm.moveToFront(it) },
            reorder = { vm.reorder(it) },
            cleanup = { days -> app.update { it.copy(cleanupDays = days) } },
        ),
    )
}

private fun DownloadState.active() = this == DownloadState.RUNNING || this == DownloadState.FAILED

private fun DownloadState.waiting() = this == DownloadState.QUEUED || this == DownloadState.PAUSED

@Composable
fun DownloadsContent(
    transfers: List<Transfer>,
    network: NetworkState,
    free: Long?,
    used: Long,
    settings: AppSettings,
    tab: DownloadsTab,
    actions: DownloadsActions,
) {
    val colors = KodexTheme.colors
    val active = transfers.filter { it.row.state.active() }
    val queue = transfers.filter { it.row.state.waiting() }.sortedBy { it.row.position }
    val history = transfers.filter { it.row.state == DownloadState.DONE }.sortedByDescending { it.row.finishedAt ?: it.row.requestedAt }
    val going = transfers.any { it.row.state == DownloadState.RUNNING || it.row.state == DownloadState.QUEUED }
    val paused = transfers.any { it.row.state == DownloadState.PAUSED }
    Scaffold(
        topBar = {
            BrandBar(stringResource(R.string.tab_downloads)) {
                if (going) {
                    OutlinedButton(
                        onClick = actions.pauseAll,
                        modifier = Modifier.padding(end = 8.dp).testTag("pause-all"),
                        colors = ButtonDefaults.outlinedButtonColors(containerColor = colors.surface1, contentColor = colors.text),
                        border = BorderStroke(1.dp, colors.border),
                    ) {
                        Icon(Icons.Filled.Pause, contentDescription = null, tint = colors.accentText)
                        Spacer(Modifier.width(6.dp))
                        Text(stringResource(R.string.pause_all))
                    }
                } else if (paused) {
                    Button(onClick = actions.resumeAll, modifier = Modifier.padding(end = 8.dp).testTag("resume-all")) {
                        Icon(Icons.Filled.PlayArrow, contentDescription = null)
                        Spacer(Modifier.width(6.dp))
                        Text(stringResource(R.string.resume_all))
                    }
                }
            }
        },
        containerColor = colors.background,
    ) { padding ->
        Box(Modifier.fillMaxSize().padding(padding), contentAlignment = Alignment.TopCenter) {
            LazyColumn(
                Modifier.readable(900.dp).fillMaxSize().testTag("downloads"),
                contentPadding = PaddingValues(start = 16.dp, end = 16.dp, top = 4.dp, bottom = 32.dp),
                verticalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                item(key = "tabs") {
                    LazyRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        item { Pill(stringResource(R.string.downloads_active), tab == DownloadsTab.ACTIVE, { actions.tab(DownloadsTab.ACTIVE) }, count = active.size) }
                        item { Pill(stringResource(R.string.downloads_queue), tab == DownloadsTab.QUEUE, { actions.tab(DownloadsTab.QUEUE) }, count = queue.size) }
                        item { Pill(stringResource(R.string.downloads_history), tab == DownloadsTab.HISTORY, { actions.tab(DownloadsTab.HISTORY) }, count = history.size) }
                    }
                }
                item(key = "summary") { Summary(transfers, network, free, used, settings) }
                when (tab) {
                    DownloadsTab.ACTIVE -> {
                        if (active.isEmpty()) item(key = "none") { Quiet(stringResource(if (queue.isEmpty()) R.string.downloads_nothing_active else R.string.downloads_waiting_turn)) }
                        items(active, key = { it.row.bookId }) { ActiveCard(it, settings, actions) }
                    }
                    DownloadsTab.QUEUE -> queueItems(queue, settings, actions)
                    DownloadsTab.HISTORY -> {
                        if (history.isEmpty()) item(key = "none") { Quiet(stringResource(R.string.downloads_empty)) }
                        items(history, key = { it.row.bookId }) { HistoryRow(it.row, settings, actions) }
                    }
                }
                item(key = "cleanup") { Cleanup(settings.cleanupDays, actions) }
            }
        }
    }
}

@Composable
private fun Quiet(text: String) {
    Text(text, style = MaterialTheme.typography.bodyMedium, color = KodexTheme.colors.textMuted, modifier = Modifier.padding(vertical = 16.dp))
}

/** How fast everything comes, how much is left, the network rule, and the room on the device. */
@Composable
private fun Summary(transfers: List<Transfer>, network: NetworkState, free: Long?, used: Long, settings: AppSettings) {
    val colors = KodexTheme.colors
    val coming = transfers.filter { it.row.state == DownloadState.RUNNING || it.row.state == DownloadState.QUEUED }
    val rate = coming.sumOf { it.rate }
    val total = coming.sumOf { it.row.total }
    val done = coming.sumOf { it.row.bytes }
    val running = coming.count { it.row.state == DownloadState.RUNNING }
    KodexCard(Modifier.fillMaxWidth().testTag("downloads-summary")) {
        Row(verticalAlignment = Alignment.Top) {
            Column(Modifier.weight(1f)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Icon(Icons.Filled.ArrowDownward, contentDescription = null, tint = colors.offlineText, modifier = Modifier.size(20.dp))
                    Spacer(Modifier.width(4.dp))
                    Text(speed(rate), style = MaterialTheme.typography.headlineLarge, color = colors.text)
                }
                Text(
                    if (running > 0) stringResource(R.string.downloads_running_count, running) else stringResource(R.string.downloads_idle),
                    style = MaterialTheme.typography.bodyMedium, color = colors.textMuted,
                )
            }
            if (total > done) {
                Column(horizontalAlignment = Alignment.End) {
                    Text(size(total - done), style = MaterialTheme.typography.titleLarge, color = colors.accentText)
                    Text(stringResource(R.string.downloads_left), style = MaterialTheme.typography.bodyMedium, color = colors.textMuted)
                }
            }
        }
        if (total > 0) {
            Spacer(Modifier.height(14.dp))
            Box(Modifier.fillMaxWidth().height(6.dp).clip(CircleShape).background(colors.surface3)) {
                Box(
                    Modifier.fillMaxWidth((done.toFloat() / total).coerceIn(0f, 1f)).height(6.dp).clip(CircleShape)
                        .background(Brush.horizontalGradient(listOf(colors.accent, colors.offline))),
                )
            }
        }
        Spacer(Modifier.height(14.dp))
        Row(verticalAlignment = Alignment.CenterVertically) {
            val waitsForWifi = settings.wifiOnly && !network.unmetered
            Icon(if (network.connected && !waitsForWifi) Icons.Filled.Wifi else Icons.Filled.WifiOff, contentDescription = null,
                tint = if (waitsForWifi || !network.connected) colors.danger else colors.textMuted, modifier = Modifier.size(18.dp))
            Spacer(Modifier.width(6.dp))
            Text(
                stringResource(
                    when {
                        !network.connected -> R.string.network_none
                        waitsForWifi -> R.string.network_waits_for_wifi
                        settings.wifiOnly -> R.string.network_wifi_only
                        else -> R.string.network_any
                    },
                ),
                style = MaterialTheme.typography.bodySmall, color = colors.textMuted, modifier = Modifier.weight(1f),
            )
            Icon(Icons.Filled.SdStorage, contentDescription = null, tint = colors.offlineText, modifier = Modifier.size(18.dp))
            Spacer(Modifier.width(6.dp))
            Text(
                listOfNotNull(free?.let { stringResource(R.string.storage_free, size(it)) }, stringResource(R.string.storage_used, size(used)))
                    .joinToString(" · "),
                style = MaterialTheme.typography.bodySmall, color = colors.textMuted,
            )
        }
    }
}

@Composable
private fun Thumb(row: DownloadRow, settings: AppSettings) {
    Box {
        Cover(row.bookId, width = 64.dp, corner = 8.dp)
        MediaBadge(mediaKind(row.libraryType, row.format), row.format, settings.rtl(row.libraryType), Modifier.padding(3.dp))
    }
}

@Composable
private fun subtitle(row: DownloadRow): String? =
    listOfNotNull(row.seriesTitle, numberLabel(row.number, "issue", row.libraryType)).joinToString(" · ").ifBlank { null }

/** A download on its way (or one that failed): how far, how fast, and pause or cancel. */
@Composable
private fun ActiveCard(transfer: Transfer, settings: AppSettings, actions: DownloadsActions) {
    val colors = KodexTheme.colors
    val row = transfer.row
    val failed = row.state == DownloadState.FAILED
    Surface(
        shape = MaterialTheme.shapes.medium,
        color = if (failed) colors.dangerSoft else colors.surface1,
        border = BorderStroke(1.dp, if (failed) colors.danger.copy(alpha = 0.4f) else colors.border),
        modifier = Modifier.fillMaxWidth().clickable { actions.open(row.bookId) }.testTag("download-${row.bookId}"),
    ) {
        Row(Modifier.padding(12.dp), horizontalArrangement = Arrangement.spacedBy(14.dp)) {
            Thumb(row, settings)
            Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                Row(verticalAlignment = Alignment.Top) {
                    Column(Modifier.weight(1f)) {
                        Text(row.title, style = MaterialTheme.typography.titleMedium, color = colors.text, maxLines = 2, overflow = TextOverflow.Ellipsis)
                        subtitle(row)?.let { Text(it, style = MaterialTheme.typography.bodySmall, color = colors.textMuted, maxLines = 1) }
                    }
                    if (!failed) {
                        IconButton(onClick = { actions.pause(row.bookId) }, modifier = Modifier.testTag("pause-${row.bookId}")) {
                            Icon(Icons.Filled.Pause, contentDescription = stringResource(R.string.pause), tint = colors.text)
                        }
                    }
                    IconButton(onClick = { actions.remove(row.bookId) }) {
                        Icon(Icons.Filled.Close, contentDescription = stringResource(R.string.cancel_download), tint = colors.textMuted)
                    }
                }
                if (failed) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Icon(Icons.Filled.CloudOff, contentDescription = null, tint = colors.danger, modifier = Modifier.size(16.dp))
                        Spacer(Modifier.width(6.dp))
                        Text(row.error ?: stringResource(R.string.download_failed_short), style = MaterialTheme.typography.bodySmall,
                            color = colors.danger, maxLines = 2, overflow = TextOverflow.Ellipsis)
                    }
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text(stringResource(R.string.attempt_of, row.attempts.coerceAtLeast(1), Downloads.ATTEMPTS).uppercase(),
                            style = MaterialTheme.typography.labelSmall, color = colors.textMuted, modifier = Modifier.weight(1f))
                        Button(
                            onClick = { actions.resume(row.bookId) },
                            colors = ButtonDefaults.buttonColors(containerColor = colors.danger, contentColor = colors.background),
                            modifier = Modifier.testTag("retry-${row.bookId}"),
                        ) {
                            Icon(Icons.Filled.Refresh, contentDescription = null, modifier = Modifier.size(18.dp))
                            Spacer(Modifier.width(6.dp))
                            Text(stringResource(R.string.retry))
                        }
                    }
                } else {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text(
                            stringResource(R.string.bytes_of, size(row.bytes), size(row.total)),
                            style = MaterialTheme.typography.labelMedium, color = colors.text, modifier = Modifier.weight(1f),
                        )
                        if (transfer.rate > 0) {
                            val left = kotlin.math.ceil((row.total - row.bytes).coerceAtLeast(0) / transfer.rate).toLong().coerceAtLeast(1)
                            Text(speed(transfer.rate) + " · " + eta(left), style = MaterialTheme.typography.labelMedium, color = colors.offlineText)
                        }
                    }
                    val fraction = if (row.total > 0) (row.bytes.toFloat() / row.total).coerceIn(0f, 1f) else 0f
                    Box(Modifier.fillMaxWidth().height(6.dp).clip(CircleShape).background(colors.surface3)) {
                        Box(
                            Modifier.fillMaxWidth(fraction).height(6.dp).clip(CircleShape)
                                .background(Brush.horizontalGradient(listOf(colors.accent, colors.offline))),
                        )
                    }
                }
            }
        }
    }
}

/** The queue in its order; a row's handle drags it to another place, the arrow puts it first. */
private fun androidx.compose.foundation.lazy.LazyListScope.queueItems(queue: List<Transfer>, settings: AppSettings, actions: DownloadsActions) {
    if (queue.isEmpty()) {
        item(key = "none") { Quiet(stringResource(R.string.downloads_queue_empty)) }
        return
    }
    item(key = "queue") { QueueList(queue, settings, actions) }
}

@Composable
private fun QueueList(queue: List<Transfer>, settings: AppSettings, actions: DownloadsActions) {
    val colors = KodexTheme.colors
    val ids = queue.map { it.row.bookId }
    var order by remember(ids) { mutableStateOf(ids) }
    var dragging by remember { mutableStateOf<Int?>(null) }
    var offset by remember { mutableFloatStateOf(0f) }
    var height by remember { mutableFloatStateOf(1f) }
    val byId = queue.associateBy { it.row.bookId }
    val gap = with(LocalDensity.current) { 8.dp.toPx() }
    Column(Modifier.testTag("queue"), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        SectionHeader(stringResource(R.string.downloads_queue_left, queue.size))
        order.forEachIndexed { index, id ->
            val row = byId[id]?.row ?: return@forEachIndexed
            Surface(
                shape = MaterialTheme.shapes.medium,
                color = colors.surface1,
                border = BorderStroke(1.dp, if (dragging == id) colors.accent else colors.border),
                modifier = Modifier.fillMaxWidth()
                    .zIndex(if (dragging == id) 1f else 0f)
                    .graphicsLayer { translationY = if (dragging == id) offset else 0f }
                    .onSizeChanged { height = it.height.toFloat() + gap }
                    .testTag("queued-$id"),
            ) {
                Row(Modifier.padding(start = 4.dp, end = 4.dp, top = 8.dp, bottom = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                    Box(
                        Modifier.size(44.dp).pointerInput(id) {
                            detectDragGestures(
                                onDragStart = {
                                    dragging = id
                                    offset = 0f
                                },
                                onDrag = { change, amount ->
                                    change.consume()
                                    offset += amount.y
                                    val at = order.indexOf(id)
                                    if (offset > height / 2 && at < order.lastIndex) {
                                        order = order.toMutableList().apply { add(at + 1, removeAt(at)) }
                                        offset -= height
                                    } else if (offset < -height / 2 && at > 0) {
                                        order = order.toMutableList().apply { add(at - 1, removeAt(at)) }
                                        offset += height
                                    }
                                },
                                onDragEnd = {
                                    dragging = null
                                    offset = 0f
                                    actions.reorder(order)
                                },
                                onDragCancel = {
                                    dragging = null
                                    offset = 0f
                                },
                            )
                        },
                        contentAlignment = Alignment.Center,
                    ) { Icon(Icons.Filled.DragIndicator, contentDescription = stringResource(R.string.drag_to_reorder), tint = colors.textMuted) }
                    Text("#${index + 1}", style = MaterialTheme.typography.labelLarge, color = colors.accentText, modifier = Modifier.width(34.dp))
                    Thumb(row, settings)
                    Spacer(Modifier.width(12.dp))
                    Column(Modifier.weight(1f)) {
                        Text(row.title, style = MaterialTheme.typography.titleSmall, color = colors.text, maxLines = 2, overflow = TextOverflow.Ellipsis)
                        Text(
                            listOfNotNull(
                                subtitle(row),
                                size(row.total),
                                if (row.state == DownloadState.PAUSED) stringResource(R.string.download_paused) else null,
                            ).joinToString(" · "),
                            style = MaterialTheme.typography.bodySmall, color = colors.textMuted, maxLines = 1, overflow = TextOverflow.Ellipsis,
                        )
                    }
                    if (row.state == DownloadState.PAUSED) {
                        IconButton(onClick = { actions.resume(row.bookId) }) {
                            Icon(Icons.Filled.PlayArrow, contentDescription = stringResource(R.string.resume), tint = colors.offlineText)
                        }
                    } else {
                        IconButton(onClick = { actions.pause(row.bookId) }) {
                            Icon(Icons.Filled.Pause, contentDescription = stringResource(R.string.pause), tint = colors.textMuted)
                        }
                    }
                    IconButton(onClick = { actions.moveToFront(row.bookId) }, enabled = index > 0) {
                        Icon(Icons.Filled.VerticalAlignTop, contentDescription = stringResource(R.string.move_first),
                            tint = if (index > 0) colors.text else colors.textFaint)
                    }
                    IconButton(onClick = { actions.remove(row.bookId) }) {
                        Icon(Icons.Filled.Delete, contentDescription = stringResource(R.string.remove_download), tint = colors.textMuted)
                    }
                }
            }
        }
    }
}

@Composable
private fun HistoryRow(row: DownloadRow, settings: AppSettings, actions: DownloadsActions) {
    val colors = KodexTheme.colors
    Row(
        Modifier.fillMaxWidth().clip(MaterialTheme.shapes.medium).clickable { actions.open(row.bookId) }.padding(vertical = 4.dp)
            .testTag("download-${row.bookId}"),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        Thumb(row, settings)
        Column(Modifier.weight(1f)) {
            Text(row.title, style = MaterialTheme.typography.titleSmall, color = colors.text, maxLines = 2, overflow = TextOverflow.Ellipsis)
            subtitle(row)?.let { Text(it, style = MaterialTheme.typography.bodySmall, color = colors.textMuted, maxLines = 1) }
            Text(
                listOfNotNull(
                    size(row.bytes),
                    row.finishedAt?.let { DateFormat.getDateInstance(DateFormat.MEDIUM).format(Date(it)) },
                    if (row.onCard) stringResource(R.string.storage_card) else null,
                    if (row.automatic) stringResource(R.string.download_automatic) else null,
                ).joinToString(" · "),
                style = MaterialTheme.typography.bodySmall, color = colors.offlineText,
            )
        }
        IconButton(onClick = { actions.remove(row.bookId) }, modifier = Modifier.heightIn(min = 48.dp)) {
            Icon(Icons.Filled.Delete, contentDescription = stringResource(R.string.remove_download), tint = colors.textMuted)
        }
    }
}

/** "Clean up": downloads of finished books go after this many days. */
@Composable
private fun Cleanup(days: Int, actions: DownloadsActions) {
    val colors = KodexTheme.colors
    KodexCard(Modifier.fillMaxWidth().testTag("cleanup")) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Box(Modifier.size(40.dp).clip(RoundedCornerShape(10.dp)).background(colors.offlineSoft), contentAlignment = Alignment.Center) {
                Icon(Icons.Filled.CleaningServices, contentDescription = null, tint = colors.offlineText)
            }
            Spacer(Modifier.width(12.dp))
            Column(Modifier.weight(1f)) {
                Text(stringResource(R.string.cleanup_title), style = MaterialTheme.typography.titleSmall, color = colors.text)
                Text(
                    if (days > 0) pluralStringResource(R.plurals.cleanup_on, days, days) else stringResource(R.string.cleanup_off),
                    style = MaterialTheme.typography.bodySmall, color = colors.textMuted,
                )
            }
        }
        Spacer(Modifier.height(12.dp))
        LazyRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            items(CLEANUP_DAYS) { n ->
                Pill(if (n == 0) stringResource(R.string.off) else stringResource(R.string.days_short, n), days == n, { actions.cleanup(n) })
            }
        }
    }
}

val CLEANUP_DAYS = listOf(0, 1, 7, 14, 30)

/** "18,4 MB/s". */
fun speed(bytesPerSecond: Double): String = size(bytesPerSecond.toLong()) + "/s"

/** "12 s", "4 min", "1 h 5 min". */
fun eta(seconds: Long): String = when {
    seconds < 60 -> "$seconds s"
    seconds < 3600 -> "${seconds / 60} min"
    else -> "${seconds / 3600} h ${seconds % 3600 / 60} min"
}
