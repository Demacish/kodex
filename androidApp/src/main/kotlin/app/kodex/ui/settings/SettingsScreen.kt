package app.kodex.ui.settings

import android.os.Build
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
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
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.Logout
import androidx.compose.material.icons.automirrored.filled.MenuBook
import androidx.compose.material.icons.filled.Brightness2
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.CleaningServices
import androidx.compose.material.icons.filled.Dns
import androidx.compose.material.icons.filled.DownloadForOffline
import androidx.compose.material.icons.filled.Info
import androidx.compose.material.icons.filled.Palette
import androidx.compose.material.icons.filled.Sync
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.pluralStringResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import app.kodex.BuildConfig
import app.kodex.R
import app.kodex.data.Accent
import app.kodex.data.AppSettings
import app.kodex.data.CardDensity
import app.kodex.data.ImageMode
import app.kodex.data.PageFilter
import app.kodex.data.PageFit
import app.kodex.data.StorageTarget
import app.kodex.data.ThemeChoice
import app.kodex.data.db.CatalogCounts
import app.kodex.shared.reader.TapLayout
import app.kodex.sync.SyncStatus
import app.kodex.ui.AppViewModel
import app.kodex.ui.LocalSession
import app.kodex.ui.components.BrandBar
import app.kodex.ui.components.Pill
import app.kodex.ui.components.message
import app.kodex.ui.components.readable
import app.kodex.ui.components.size
import app.kodex.ui.theme.KodexTheme
import app.kodex.ui.theme.kodexColors
import java.text.DateFormat
import java.util.Date

/** What the settings show besides the settings themselves. */
data class SettingsInfo(
    val username: String = "",
    val server: String = "",
    val syncedAt: Long? = null,
    val pending: Int = 0,
    val status: SyncStatus = SyncStatus(),
    val counts: CatalogCounts? = null,
    val cardAvailable: Boolean = false,
    val freeInternal: Long? = null,
    val freeCard: Long? = null,
    val cacheBytes: Long? = null,
)

class SettingsActions(
    val update: ((AppSettings) -> AppSettings) -> Unit = {},
    val syncNow: () -> Unit = {},
    val clearCache: () -> Unit = {},
    val logout: () -> Unit = {},
)

@Composable
fun SettingsScreen(app: AppViewModel) {
    val settings by app.settings.collectAsStateWithLifecycle()
    val sync by app.syncState.collectAsStateWithLifecycle(initialValue = null)
    val pending by app.pending.collectAsStateWithLifecycle(initialValue = 0)
    val status by app.syncStatus.collectAsStateWithLifecycle(initialValue = SyncStatus())
    val counts by app.counts.collectAsStateWithLifecycle(initialValue = null)
    val cache by app.cacheBytes.collectAsStateWithLifecycle()
    LaunchedEffect(Unit) { app.measureCache() }
    val session = LocalSession.current
    SettingsContent(
        settings,
        SettingsInfo(
            username = session?.username.orEmpty(),
            server = session?.server.orEmpty(),
            syncedAt = sync?.syncedAt,
            pending = pending,
            status = status,
            counts = counts,
            cardAvailable = app.cardAvailable,
            freeInternal = app.freeBytes(StorageTarget.INTERNAL),
            freeCard = if (app.cardAvailable) app.freeBytes(StorageTarget.CARD) else null,
            cacheBytes = cache,
        ),
        SettingsActions(update = app::update, syncNow = app::syncNow, clearCache = app::clearCache, logout = app::logout),
    )
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
fun SettingsContent(settings: AppSettings, info: SettingsInfo, actions: SettingsActions) {
    val colors = KodexTheme.colors
    val update = actions.update
    Scaffold(topBar = { BrandBar(stringResource(R.string.tab_settings)) }, containerColor = colors.background) { padding ->
        Box(Modifier.fillMaxSize().padding(padding), contentAlignment = Alignment.TopCenter) {
            Column(
                Modifier.readable().verticalScroll(rememberScrollState()).padding(horizontal = 16.dp).padding(bottom = 32.dp).testTag("settings"),
                verticalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                ServerCard(info, actions)

                Section(Icons.Filled.DownloadForOffline, stringResource(R.string.settings_downloads), colors.offlineText)
                Group {
                    Toggle(stringResource(R.string.settings_wifi_only), stringResource(R.string.settings_wifi_only_help), settings.wifiOnly) { on ->
                        update { it.copy(wifiOnly = on) }
                    }
                    Choices(stringResource(R.string.settings_concurrency), stringResource(R.string.settings_concurrency_help),
                        listOf(1, 2, 4).map { it to it.toString() }, settings.concurrency) { n -> update { it.copy(concurrency = n) } }
                    if (info.cardAvailable || settings.storage == StorageTarget.CARD) {
                        Choices(
                            stringResource(R.string.settings_storage),
                            stringResource(R.string.settings_storage_help),
                            listOf(
                                StorageTarget.INTERNAL to stringResource(R.string.storage_internal) + (info.freeInternal?.let { " · " + size(it) } ?: ""),
                                StorageTarget.CARD to stringResource(R.string.storage_card) + (info.freeCard?.let { " · " + size(it) } ?: ""),
                            ),
                            settings.storage,
                        ) { target -> update { it.copy(storage = target) } }
                    }
                    Choices(stringResource(R.string.settings_auto_next), stringResource(R.string.settings_auto_next_help),
                        listOf(0, 1, 2, 3, 5).map { it to if (it == 0) stringResource(R.string.off) else it.toString() }, settings.autoNext) { n ->
                        update { it.copy(autoNext = n) }
                    }
                    Choices(stringResource(R.string.cleanup_title), stringResource(R.string.cleanup_help),
                        listOf(0, 1, 7, 14, 30).map { it to if (it == 0) stringResource(R.string.off) else stringResource(R.string.days_short, it) },
                        settings.cleanupDays) { n -> update { it.copy(cleanupDays = n) } }
                }

                Section(Icons.AutoMirrored.Filled.MenuBook, stringResource(R.string.settings_reading), colors.accentText)
                Group {
                    val modes = listOf(
                        ImageMode.PAGED_LTR to stringResource(R.string.mode_ltr_short),
                        ImageMode.PAGED_RTL to stringResource(R.string.mode_rtl_short),
                        ImageMode.VERTICAL to stringResource(R.string.mode_vertical),
                    )
                    Choices(stringResource(R.string.settings_mode_manga), null, modes, settings.mangaMode) { m -> update { it.copy(mangaMode = m) } }
                    Choices(stringResource(R.string.settings_mode_comics), null, modes, settings.comicsMode) { m -> update { it.copy(comicsMode = m) } }
                    Choices(stringResource(R.string.settings_mode_books), stringResource(R.string.settings_mode_books_help), modes, settings.booksMode) { m ->
                        update { it.copy(booksMode = m) }
                    }
                    Choices(
                        stringResource(R.string.settings_fit), null,
                        listOf(
                            PageFit.PAGE to stringResource(R.string.fit_page),
                            PageFit.WIDTH to stringResource(R.string.fit_width),
                            PageFit.HEIGHT to stringResource(R.string.fit_height),
                            PageFit.ORIGINAL to stringResource(R.string.fit_original),
                        ),
                        settings.fit,
                    ) { fit -> update { it.copy(fit = fit) } }
                    Toggle(stringResource(R.string.settings_spreads), stringResource(R.string.settings_spreads_help), settings.spreads) { on ->
                        update { it.copy(spreads = on) }
                    }
                    Toggle(stringResource(R.string.settings_cover_alone), null, settings.coverAlone) { on -> update { it.copy(coverAlone = on) } }
                    Toggle(stringResource(R.string.settings_split_wide), stringResource(R.string.settings_split_wide_help), settings.splitWide) { on ->
                        update { it.copy(splitWide = on) }
                    }
                    Choices(
                        stringResource(R.string.settings_tap_layout), null,
                        listOf(TapLayout.SIDES to stringResource(R.string.tap_sides), TapLayout.EDGES to stringResource(R.string.tap_edges),
                            TapLayout.OFF to stringResource(R.string.off)),
                        settings.tapLayout,
                    ) { layout -> update { it.copy(tapLayout = layout) } }
                    Choices(
                        stringResource(R.string.settings_filter), null,
                        listOf(
                            PageFilter.NONE to stringResource(R.string.filter_none),
                            PageFilter.GRAYSCALE to stringResource(R.string.filter_grayscale),
                            PageFilter.SEPIA to stringResource(R.string.filter_sepia),
                            PageFilter.INVERT to stringResource(R.string.filter_invert),
                        ),
                        settings.filter,
                    ) { filter -> update { it.copy(filter = filter) } }
                    Toggle(stringResource(R.string.settings_trim), stringResource(R.string.settings_trim_help), settings.trim) { on ->
                        update { it.copy(trim = on) }
                    }
                    Toggle(stringResource(R.string.settings_pure_black), stringResource(R.string.settings_pure_black_help), settings.pureBlack) { on ->
                        update { it.copy(pureBlack = on) }
                    }
                    Toggle(stringResource(R.string.settings_keep_screen_on), null, settings.keepScreenOn) { on -> update { it.copy(keepScreenOn = on) } }
                }

                Section(Icons.Filled.Palette, stringResource(R.string.settings_appearance), colors.accentText)
                Group {
                    Choices(
                        stringResource(R.string.settings_theme), null,
                        listOf(ThemeChoice.SYSTEM to stringResource(R.string.theme_system), ThemeChoice.LIGHT to stringResource(R.string.theme_light),
                            ThemeChoice.DARK to stringResource(R.string.theme_dark)),
                        settings.theme,
                    ) { theme -> update { it.copy(theme = theme) } }
                    AccentChoice(settings.accent) { accent -> update { it.copy(accent = accent) } }
                    Choices(
                        stringResource(R.string.settings_density), stringResource(R.string.settings_density_help),
                        listOf(CardDensity.COMPACT to stringResource(R.string.density_compact), CardDensity.LARGE to stringResource(R.string.density_large)),
                        settings.density,
                    ) { density -> update { it.copy(density = density) } }
                }

                Section(Icons.Filled.CleaningServices, stringResource(R.string.settings_maintenance), colors.textMuted)
                Group {
                    Line(
                        stringResource(R.string.settings_cache),
                        info.cacheBytes?.let { stringResource(R.string.settings_cache_size, size(it)) } ?: stringResource(R.string.settings_cache_measuring),
                    ) {
                        OutlinedButton(
                            onClick = actions.clearCache,
                            border = BorderStroke(1.dp, colors.border),
                            colors = ButtonDefaults.outlinedButtonColors(containerColor = colors.surface2, contentColor = colors.accentText),
                            modifier = Modifier.testTag("clear-cache"),
                        ) { Text(stringResource(R.string.settings_cache_clear)) }
                    }
                    Line(stringResource(R.string.settings_about), stringResource(R.string.version, BuildConfig.VERSION_NAME), icon = Icons.Filled.Info)
                    Column(Modifier.fillMaxWidth().padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        OutlinedButton(
                            onClick = actions.logout,
                            modifier = Modifier.testTag("logout"),
                            border = BorderStroke(1.dp, colors.danger.copy(alpha = 0.5f)),
                            colors = ButtonDefaults.outlinedButtonColors(contentColor = colors.danger),
                        ) {
                            Icon(Icons.AutoMirrored.Filled.Logout, contentDescription = null)
                            Spacer(Modifier.width(8.dp))
                            Text(stringResource(R.string.logout))
                        }
                        Text(stringResource(R.string.logout_help), style = MaterialTheme.typography.bodySmall, color = colors.textMuted)
                    }
                }
            }
        }
    }
}

/** The server: whether it answers, when the catalog last came, and a sync now. */
@Composable
private fun ServerCard(info: SettingsInfo, actions: SettingsActions) {
    val colors = KodexTheme.colors
    val status = info.status
    val problem = status.problem
    Surface(
        shape = MaterialTheme.shapes.large,
        color = colors.surface1,
        border = BorderStroke(1.dp, colors.border),
        modifier = Modifier.fillMaxWidth().padding(top = 4.dp).testTag("server-card"),
    ) {
        Column(Modifier.padding(16.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Box {
                    Box(Modifier.size(52.dp).clip(RoundedCornerShape(14.dp)).background(colors.surface3), contentAlignment = Alignment.Center) {
                        Icon(Icons.Filled.Dns, contentDescription = null, tint = colors.accentText)
                    }
                    Box(
                        Modifier.align(Alignment.BottomEnd).size(14.dp).clip(CircleShape)
                            .background(if (problem != null && !status.busy) colors.danger else colors.offline)
                            .border(2.dp, colors.surface1, CircleShape),
                    )
                }
                Spacer(Modifier.width(14.dp))
                Column(Modifier.weight(1f)) {
                    Text(info.server.removePrefix("https://").removePrefix("http://"), style = MaterialTheme.typography.titleMedium,
                        color = colors.text, maxLines = 1, overflow = TextOverflow.Ellipsis)
                    Text(
                        when {
                            status.running -> stringResource(R.string.sync_running)
                            status.waiting -> stringResource(R.string.sync_waiting)
                            else -> info.syncedAt?.let {
                                stringResource(R.string.synced_at, DateFormat.getDateTimeInstance(DateFormat.SHORT, DateFormat.SHORT).format(Date(it)))
                            } ?: stringResource(R.string.settings_never_synced)
                        },
                        style = MaterialTheme.typography.bodySmall, color = colors.textMuted,
                    )
                }
                Button(onClick = actions.syncNow, enabled = !status.busy, modifier = Modifier.testTag("sync-now"), shape = MaterialTheme.shapes.small) {
                    if (status.busy) {
                        CircularProgressIndicator(Modifier.size(16.dp), strokeWidth = 2.dp, color = colors.onAccent)
                    } else {
                        Icon(Icons.Filled.Sync, contentDescription = null, modifier = Modifier.size(18.dp))
                    }
                    Spacer(Modifier.width(6.dp))
                    Text(stringResource(R.string.settings_sync_now))
                }
            }
            if (problem != null && !status.busy) {
                Spacer(Modifier.height(10.dp))
                Text(problem.message(), color = colors.danger, style = MaterialTheme.typography.bodyMedium, modifier = Modifier.testTag("sync-problem"))
            }
            Spacer(Modifier.height(14.dp))
            Row(
                Modifier.fillMaxWidth().clip(MaterialTheme.shapes.medium).background(colors.surface2).padding(vertical = 10.dp),
                horizontalArrangement = Arrangement.SpaceEvenly,
            ) {
                Stat(stringResource(R.string.stat_user), info.username, colors.accentText)
                Stat(stringResource(R.string.stat_series), info.counts?.series?.toString() ?: "–", colors.text)
                Stat(stringResource(R.string.stat_books), info.counts?.books?.toString() ?: "–", colors.text)
                Stat(stringResource(R.string.stat_waiting), info.pending.toString(), if (info.pending > 0) colors.accentText else colors.offlineText)
            }
            if (info.pending > 0) {
                Spacer(Modifier.height(8.dp))
                Text(pluralStringResource(R.plurals.settings_positions_waiting, info.pending, info.pending), style = MaterialTheme.typography.bodySmall,
                    color = colors.textMuted)
            }
        }
    }
}

@Composable
private fun Stat(label: String, value: String, tint: Color) {
    Column(horizontalAlignment = Alignment.CenterHorizontally) {
        Text(label.uppercase(), style = MaterialTheme.typography.labelSmall, color = KodexTheme.colors.textMuted)
        Text(value, style = MaterialTheme.typography.titleMedium, color = tint, maxLines = 1, overflow = TextOverflow.Ellipsis)
    }
}

@Composable
private fun Section(icon: ImageVector, title: String, tint: Color) {
    Row(Modifier.padding(top = 12.dp, start = 4.dp), verticalAlignment = Alignment.CenterVertically) {
        Icon(icon, contentDescription = null, tint = tint, modifier = Modifier.size(20.dp))
        Spacer(Modifier.width(8.dp))
        Text(title.uppercase(), style = MaterialTheme.typography.titleSmall, color = tint)
    }
}

/** Settings that belong together, on one card with lines between them. */
@Composable
private fun Group(content: @Composable ColumnScope.() -> Unit) {
    val colors = KodexTheme.colors
    Surface(shape = MaterialTheme.shapes.large, color = colors.surface1, border = BorderStroke(1.dp, colors.border), modifier = Modifier.fillMaxWidth()) {
        Column(content = content)
    }
}

@Composable
private fun Divider() = HorizontalDivider(color = KodexTheme.colors.borderSubtle, modifier = Modifier.padding(horizontal = 16.dp))

@Composable
private fun Line(title: String, help: String?, icon: ImageVector? = null, trailing: @Composable () -> Unit = {}) {
    val colors = KodexTheme.colors
    Row(Modifier.fillMaxWidth().heightIn(min = 64.dp).padding(horizontal = 16.dp, vertical = 10.dp), verticalAlignment = Alignment.CenterVertically) {
        icon?.let {
            Icon(it, contentDescription = null, tint = colors.textMuted, modifier = Modifier.size(20.dp))
            Spacer(Modifier.width(14.dp))
        }
        Column(Modifier.weight(1f)) {
            Text(title, style = MaterialTheme.typography.titleMedium, color = colors.text)
            help?.let { Text(it, style = MaterialTheme.typography.bodySmall, color = colors.textMuted) }
        }
        trailing()
    }
    Divider()
}

@Composable
private fun Toggle(title: String, help: String?, checked: Boolean, onChange: (Boolean) -> Unit) {
    Row(
        Modifier.fillMaxWidth().clickable { onChange(!checked) }.heightIn(min = 64.dp).padding(horizontal = 16.dp, vertical = 10.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(Modifier.weight(1f)) {
            Text(title, style = MaterialTheme.typography.titleMedium, color = KodexTheme.colors.text)
            help?.let { Text(it, style = MaterialTheme.typography.bodySmall, color = KodexTheme.colors.textMuted) }
        }
        Spacer(Modifier.width(12.dp))
        Switch(checked = checked, onCheckedChange = onChange)
    }
    Divider()
}

/** One of a few choices, as pills that wrap onto more rows when they don't fit. */
@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun <T> Choices(title: String, help: String?, options: List<Pair<T, String>>, selected: T, onSelect: (T) -> Unit) {
    Column(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 12.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        Column {
            Text(title, style = MaterialTheme.typography.titleMedium, color = KodexTheme.colors.text)
            help?.let { Text(it, style = MaterialTheme.typography.bodySmall, color = KodexTheme.colors.textMuted) }
        }
        FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            options.forEach { (value, label) -> Pill(label, selected == value, { onSelect(value) }) }
        }
    }
    Divider()
}

/** The accent's colours as swatches; the device's own on Android 12 and later. */
@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun AccentChoice(selected: Accent, onSelect: (Accent) -> Unit) {
    val colors = KodexTheme.colors
    val options = Accent.entries.filter { it != Accent.DEVICE || Build.VERSION.SDK_INT >= Build.VERSION_CODES.S }
    Column(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 12.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        Text(stringResource(R.string.settings_accent), style = MaterialTheme.typography.titleMedium, color = colors.text)
        FlowRow(horizontalArrangement = Arrangement.spacedBy(12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            options.forEach { accent ->
                val swatch = if (accent == Accent.DEVICE) MaterialTheme.colorScheme.primary.takeIf { selected == Accent.DEVICE }
                    ?: Color(0xFF8E9AAF) else kodexColors(accent, colors.dark).accent
                Column(
                    Modifier.clip(MaterialTheme.shapes.small).clickable { onSelect(accent) }.padding(4.dp).testTag("accent-${accent.name.lowercase()}"),
                    horizontalAlignment = Alignment.CenterHorizontally,
                ) {
                    Box(
                        Modifier.size(40.dp).clip(CircleShape).background(swatch)
                            .border(2.dp, if (selected == accent) colors.text else Color.Transparent, CircleShape),
                        contentAlignment = Alignment.Center,
                    ) {
                        when {
                            selected == accent -> Icon(Icons.Filled.Check, contentDescription = null, tint = colors.onAccent, modifier = Modifier.size(20.dp))
                            accent == Accent.DEVICE -> Icon(Icons.Filled.Brightness2, contentDescription = null, tint = Color.White, modifier = Modifier.size(18.dp))
                        }
                    }
                    Text(stringResource(accentLabel(accent)), style = MaterialTheme.typography.labelMedium, color = colors.textMuted)
                }
            }
        }
    }
    Divider()
}

private fun accentLabel(accent: Accent): Int = when (accent) {
    Accent.AMBER -> R.string.accent_amber
    Accent.CORAL -> R.string.accent_coral
    Accent.SKY -> R.string.accent_sky
    Accent.VIOLET -> R.string.accent_violet
    Accent.DEVICE -> R.string.accent_device
}
