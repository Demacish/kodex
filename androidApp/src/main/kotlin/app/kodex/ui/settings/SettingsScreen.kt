package app.kodex.ui.settings

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.FilterChip
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.ListItem
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.pluralStringResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import app.kodex.BuildConfig
import app.kodex.R
import app.kodex.data.ImageMode
import app.kodex.data.PageFilter
import app.kodex.data.ThemeChoice
import app.kodex.ui.AppViewModel
import app.kodex.ui.LocalSession
import app.kodex.shared.reader.TapLayout
import app.kodex.ui.components.Bar
import java.text.DateFormat
import java.util.Date

@Composable
fun SettingsScreen(app: AppViewModel) {
    val settings by app.settings.collectAsStateWithLifecycle()
    val sync by app.syncState.collectAsStateWithLifecycle(initialValue = null)
    val pending by app.pending.collectAsStateWithLifecycle(initialValue = 0)
    val session = LocalSession.current
    Scaffold(topBar = { Bar(stringResource(R.string.tab_settings)) }) { padding ->
        Column(Modifier.fillMaxSize().padding(padding).verticalScroll(rememberScrollState()).testTag("settings")) {
            Section(stringResource(R.string.settings_account))
            ListItem(
                headlineContent = { Text(session?.username.orEmpty()) },
                supportingContent = { Text(session?.server.orEmpty()) },
            )
            ListItem(
                headlineContent = { Text(stringResource(R.string.settings_synced)) },
                supportingContent = {
                    val at = sync?.syncedAt
                    Text(
                        listOfNotNull(
                            at?.let { DateFormat.getDateTimeInstance(DateFormat.SHORT, DateFormat.SHORT).format(Date(it)) }
                                ?: stringResource(R.string.settings_never_synced),
                            if (pending > 0) pluralStringResource(R.plurals.settings_positions_waiting, pending, pending) else null,
                        ).joinToString(" · "),
                    )
                },
                trailingContent = { OutlinedButton(onClick = app::syncNow) { Text(stringResource(R.string.settings_sync_now)) } },
            )
            HorizontalDivider()

            Section(stringResource(R.string.settings_downloads))
            Toggle(stringResource(R.string.settings_wifi_only), stringResource(R.string.settings_wifi_only_help), settings.wifiOnly) { on ->
                app.update { it.copy(wifiOnly = on) }
            }
            ListItem(
                headlineContent = { Text(stringResource(R.string.settings_auto_next)) },
                supportingContent = {
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        listOf(0, 1, 2, 3, 5).forEach { n ->
                            FilterChip(
                                selected = settings.autoNext == n,
                                onClick = { app.update { it.copy(autoNext = n) } },
                                label = { Text(if (n == 0) stringResource(R.string.off) else n.toString()) },
                            )
                        }
                    }
                },
            )
            HorizontalDivider()

            Section(stringResource(R.string.settings_reading))
            ListItem(
                headlineContent = { Text(stringResource(R.string.settings_image_mode)) },
                supportingContent = {
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        listOf(ImageMode.PAGED_LTR to R.string.mode_ltr, ImageMode.PAGED_RTL to R.string.mode_rtl, ImageMode.VERTICAL to R.string.mode_vertical)
                            .forEach { (mode, label) ->
                                FilterChip(
                                    selected = settings.imageMode == mode,
                                    onClick = { app.update { it.copy(imageMode = mode) } },
                                    label = { Text(stringResource(label)) },
                                )
                            }
                    }
                },
            )
            Toggle(stringResource(R.string.settings_spreads), stringResource(R.string.settings_spreads_help), settings.spreads) { on ->
                app.update { it.copy(spreads = on) }
            }
            Toggle(stringResource(R.string.settings_cover_alone), null, settings.coverAlone) { on -> app.update { it.copy(coverAlone = on) } }
            Toggle(stringResource(R.string.settings_split_wide), stringResource(R.string.settings_split_wide_help), settings.splitWide) { on ->
                app.update { it.copy(splitWide = on) }
            }
            Choice(
                stringResource(R.string.settings_tap_layout),
                listOf(TapLayout.SIDES to R.string.tap_sides, TapLayout.EDGES to R.string.tap_edges, TapLayout.OFF to R.string.off),
                settings.tapLayout,
            ) { layout -> app.update { it.copy(tapLayout = layout) } }
            Choice(
                stringResource(R.string.settings_filter),
                listOf(
                    PageFilter.NONE to R.string.filter_none,
                    PageFilter.GRAYSCALE to R.string.filter_grayscale,
                    PageFilter.SEPIA to R.string.filter_sepia,
                    PageFilter.INVERT to R.string.filter_invert,
                ),
                settings.filter,
            ) { filter -> app.update { it.copy(filter = filter) } }
            Toggle(stringResource(R.string.settings_trim), stringResource(R.string.settings_trim_help), settings.trim) { on ->
                app.update { it.copy(trim = on) }
            }
            Toggle(stringResource(R.string.settings_keep_screen_on), null, settings.keepScreenOn) { on ->
                app.update { it.copy(keepScreenOn = on) }
            }
            ListItem(
                headlineContent = { Text(stringResource(R.string.settings_theme)) },
                supportingContent = {
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        listOf(ThemeChoice.SYSTEM to R.string.theme_system, ThemeChoice.LIGHT to R.string.theme_light, ThemeChoice.DARK to R.string.theme_dark)
                            .forEach { (theme, label) ->
                                FilterChip(
                                    selected = settings.theme == theme,
                                    onClick = { app.update { it.copy(theme = theme) } },
                                    label = { Text(stringResource(label)) },
                                )
                            }
                    }
                },
            )
            HorizontalDivider()

            Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(onClick = app::logout, modifier = Modifier.testTag("logout")) { Text(stringResource(R.string.logout)) }
                Text(stringResource(R.string.logout_help), style = MaterialTheme.typography.bodySmall)
                Text(stringResource(R.string.version, BuildConfig.VERSION_NAME), style = MaterialTheme.typography.bodySmall)
            }
        }
    }
}

@Composable
private fun Section(title: String) {
    Text(
        title,
        style = MaterialTheme.typography.titleSmall,
        color = MaterialTheme.colorScheme.primary,
        modifier = Modifier.padding(start = 16.dp, top = 16.dp, bottom = 4.dp),
    )
}

/** One of a few choices, as chips that wrap onto more rows when they don't fit. */
@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun <T> Choice(title: String, options: List<Pair<T, Int>>, selected: T, onSelect: (T) -> Unit) {
    ListItem(
        headlineContent = { Text(title) },
        supportingContent = {
            FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                options.forEach { (value, label) ->
                    FilterChip(selected = selected == value, onClick = { onSelect(value) }, label = { Text(stringResource(label)) })
                }
            }
        },
    )
}

@Composable
private fun Toggle(title: String, help: String?, checked: Boolean, onChange: (Boolean) -> Unit) {
    ListItem(
        headlineContent = { Text(title) },
        supportingContent = if (help != null) {
            { Text(help) }
        } else {
            null
        },
        trailingContent = { Switch(checked = checked, onCheckedChange = onChange) },
    )
}
