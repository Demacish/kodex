package app.kodex.data

import android.content.Context
import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.booleanPreferencesKey
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.intPreferencesKey
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import app.kodex.shared.reader.TapLayout
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.map

enum class ImageMode { PAGED_LTR, PAGED_RTL, VERTICAL }

enum class ThemeChoice { SYSTEM, LIGHT, DARK }

/** A colour filter over comic pages. */
enum class PageFilter { NONE, GRAYSCALE, SEPIA, INVERT }

data class AppSettings(
    /** Downloads wait for Wi-Fi (an unmetered network). */
    val wifiOnly: Boolean = true,
    /** How many of the next books in a series to fetch while one is being read (0: none). */
    val autoNext: Int = 2,
    val imageMode: ImageMode = ImageMode.PAGED_LTR,
    /** Two pages side by side when the screen is wider than tall. */
    val spreads: Boolean = true,
    val coverAlone: Boolean = true,
    /** A wide page on a narrow screen as its two halves, one at a time. */
    val splitWide: Boolean = false,
    val tapLayout: TapLayout = TapLayout.SIDES,
    val filter: PageFilter = PageFilter.NONE,
    /** Cut blank margins (pages from the server; a downloaded book is shown as it is). */
    val trim: Boolean = false,
    val keepScreenOn: Boolean = true,
    val theme: ThemeChoice = ThemeChoice.SYSTEM,
)

private val Context.settingsData: DataStore<Preferences> by preferencesDataStore("settings")

class SettingsStore(private val context: Context) {
    private object Keys {
        val wifiOnly = booleanPreferencesKey("wifi_only")
        val autoNext = intPreferencesKey("auto_next")
        val imageMode = stringPreferencesKey("image_mode")
        val spreads = booleanPreferencesKey("spreads")
        val coverAlone = booleanPreferencesKey("cover_alone")
        val splitWide = booleanPreferencesKey("split_wide")
        val tapLayout = stringPreferencesKey("tap_layout")
        val filter = stringPreferencesKey("filter")
        val trim = booleanPreferencesKey("trim")
        val keepScreenOn = booleanPreferencesKey("keep_screen_on")
        val theme = stringPreferencesKey("theme")
    }

    val settings: Flow<AppSettings> = context.settingsData.data.map { it.settings() }

    suspend fun current(): AppSettings = context.settingsData.data.first().settings()

    private fun Preferences.settings(): AppSettings {
        val defaults = AppSettings()
        return AppSettings(
            wifiOnly = this[Keys.wifiOnly] ?: defaults.wifiOnly,
            autoNext = this[Keys.autoNext] ?: defaults.autoNext,
            imageMode = this[Keys.imageMode]?.let { runCatching { ImageMode.valueOf(it) }.getOrNull() } ?: defaults.imageMode,
            spreads = this[Keys.spreads] ?: defaults.spreads,
            coverAlone = this[Keys.coverAlone] ?: defaults.coverAlone,
            splitWide = this[Keys.splitWide] ?: defaults.splitWide,
            tapLayout = this[Keys.tapLayout]?.let { runCatching { TapLayout.valueOf(it) }.getOrNull() } ?: defaults.tapLayout,
            filter = this[Keys.filter]?.let { runCatching { PageFilter.valueOf(it) }.getOrNull() } ?: defaults.filter,
            trim = this[Keys.trim] ?: defaults.trim,
            keepScreenOn = this[Keys.keepScreenOn] ?: defaults.keepScreenOn,
            theme = this[Keys.theme]?.let { runCatching { ThemeChoice.valueOf(it) }.getOrNull() } ?: defaults.theme,
        )
    }

    suspend fun update(change: (AppSettings) -> AppSettings) {
        context.settingsData.edit {
            val next = change(it.settings())
            it[Keys.wifiOnly] = next.wifiOnly
            it[Keys.autoNext] = next.autoNext.coerceIn(0, 10)
            it[Keys.imageMode] = next.imageMode.name
            it[Keys.spreads] = next.spreads
            it[Keys.coverAlone] = next.coverAlone
            it[Keys.splitWide] = next.splitWide
            it[Keys.tapLayout] = next.tapLayout.name
            it[Keys.filter] = next.filter.name
            it[Keys.trim] = next.trim
            it[Keys.keepScreenOn] = next.keepScreenOn
            it[Keys.theme] = next.theme.name
        }
    }
}
