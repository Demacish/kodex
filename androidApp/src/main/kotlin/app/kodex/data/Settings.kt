package app.kodex.data

import android.content.Context
import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.booleanPreferencesKey
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.floatPreferencesKey
import androidx.datastore.preferences.core.intPreferencesKey
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import app.kodex.shared.reader.TapLayout
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.map

enum class ImageMode { PAGED_LTR, PAGED_RTL, VERTICAL }

enum class ThemeChoice { SYSTEM, LIGHT, DARK }

/** The colour of buttons, progress and the chosen tab; [DEVICE] is the device's own (Android 12+). */
/** The accent colour: Kodex's periwinkle (the default since the 2.4 look), the earlier amber, or the device's own. */
enum class Accent { KODEX, AMBER, CORAL, SKY, VIOLET, DEVICE }

/** An e-book's page colours: following the app (dark, or black with [AppSettings.pureBlack]), or chosen. */
enum class EpubTheme { AUTO, LIGHT, SEPIA, DARK, BLACK }

/** An e-book's font: the book's own, or a serif or sans-serif one. */
enum class EpubFont { PUBLISHER, SERIF, SANS }

enum class EpubSpacing { TIGHT, NORMAL, LOOSE }

enum class EpubMargins { NARROW, NORMAL, WIDE }

/** One column, two (an open book), or two when the screen is wide and lies down. */
enum class EpubColumns { AUTO, ONE, TWO }

/** How many covers fit across a phone: three ([COMPACT]) or two ([LARGE]); more on wider screens. */
enum class CardDensity { COMPACT, LARGE }

/** How a page fits the screen: all of it, the screen's width or height, or one image pixel per screen pixel. */
enum class PageFit { PAGE, WIDTH, HEIGHT, ORIGINAL }

/** Where new downloads go: the device's own storage or a memory card. */
enum class StorageTarget { INTERNAL, CARD }

/** A colour filter over comic pages. */
enum class PageFilter { NONE, GRAYSCALE, SEPIA, INVERT }

data class AppSettings(
    /** Downloads wait for Wi-Fi (an unmetered network). */
    val wifiOnly: Boolean = true,
    /** How many of the next books in a series to fetch while one is being read (0: none). */
    val autoNext: Int = 2,
    /** How many books download at once. */
    val concurrency: Int = 2,
    val storage: StorageTarget = StorageTarget.INTERNAL,
    /** Downloads of finished books go this many days after they were finished (0: never). */
    val cleanupDays: Int = 0,
    /** The reading direction a book starts in, by the kind of library it is in. */
    val mangaMode: ImageMode = ImageMode.PAGED_RTL,
    val comicsMode: ImageMode = ImageMode.PAGED_LTR,
    val booksMode: ImageMode = ImageMode.PAGED_LTR,
    val fit: PageFit = PageFit.PAGE,
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
    /** The reader's brightness, 0–1; below 0 the device's own. */
    val brightness: Float = -1f,
    /** Black around the pages (OLED), rather than the theme's background. */
    val pureBlack: Boolean = true,
    val theme: ThemeChoice = ThemeChoice.SYSTEM,
    val accent: Accent = Accent.KODEX,
    val density: CardDensity = CardDensity.COMPACT,
    val epubTheme: EpubTheme = EpubTheme.AUTO,
    val epubFont: EpubFont = EpubFont.PUBLISHER,
    /** The text's size, 1 = the book's. */
    val epubSize: Float = 1f,
    val epubSpacing: EpubSpacing = EpubSpacing.NORMAL,
    val epubMargins: EpubMargins = EpubMargins.NORMAL,
    val epubScroll: Boolean = false,
    val epubJustify: Boolean = false,
    val epubColumns: EpubColumns = EpubColumns.AUTO,
) {
    /** The direction a book in a library of [libraryType] (the server's library_type) opens in. */
    fun modeFor(libraryType: String?): ImageMode = when (libraryType?.lowercase()) {
        "manga" -> mangaMode
        "ebooks" -> booksMode
        else -> comicsMode
    }
}

private val Context.settingsData: DataStore<Preferences> by preferencesDataStore("settings")

/** The look the settings are saved under (3 = the 2.4 redesign, where Kodex's periwinkle became the default). */
private const val LOOK = 3

class SettingsStore(private val context: Context) {
    private object Keys {
        val wifiOnly = booleanPreferencesKey("wifi_only")
        val autoNext = intPreferencesKey("auto_next")
        val concurrency = intPreferencesKey("concurrency")
        val storage = stringPreferencesKey("storage")
        val cleanupDays = intPreferencesKey("cleanup_days")

        /** One direction for every book, before there was one per kind of library. */
        val imageMode = stringPreferencesKey("image_mode")
        val mangaMode = stringPreferencesKey("manga_mode")
        val comicsMode = stringPreferencesKey("comics_mode")
        val booksMode = stringPreferencesKey("books_mode")
        val fit = stringPreferencesKey("fit")
        val spreads = booleanPreferencesKey("spreads")
        val coverAlone = booleanPreferencesKey("cover_alone")
        val splitWide = booleanPreferencesKey("split_wide")
        val tapLayout = stringPreferencesKey("tap_layout")
        val filter = stringPreferencesKey("filter")
        val trim = booleanPreferencesKey("trim")
        val keepScreenOn = booleanPreferencesKey("keep_screen_on")
        val brightness = floatPreferencesKey("brightness")
        val pureBlack = booleanPreferencesKey("pure_black")
        val theme = stringPreferencesKey("theme")
        val accent = stringPreferencesKey("accent")
        /** Which look the settings were last saved under: amber, the old default, becomes Kodex's colour once. */
        val look = intPreferencesKey("look")
        val density = stringPreferencesKey("density")
        val epubTheme = stringPreferencesKey("epub_theme")
        val epubFont = stringPreferencesKey("epub_font")
        val epubSize = floatPreferencesKey("epub_size")
        val epubSpacing = stringPreferencesKey("epub_spacing")
        val epubMargins = stringPreferencesKey("epub_margins")
        val epubScroll = booleanPreferencesKey("epub_scroll")
        val epubJustify = booleanPreferencesKey("epub_justify")
        val epubColumns = stringPreferencesKey("epub_columns")
    }

    val settings: Flow<AppSettings> = context.settingsData.data.map { it.settings() }

    suspend fun current(): AppSettings = context.settingsData.data.first().settings()

    private inline fun <reified T : Enum<T>> Preferences.choice(key: Preferences.Key<String>): T? =
        this[key]?.let { name -> enumValues<T>().firstOrNull { it.name == name } }

    private fun Preferences.settings(): AppSettings {
        val defaults = AppSettings()
        // The one direction chosen before stays the comics' and the books'; manga keeps it
        // unless it was left to right, the old default.
        val old = choice<ImageMode>(Keys.imageMode)
        return AppSettings(
            wifiOnly = this[Keys.wifiOnly] ?: defaults.wifiOnly,
            autoNext = this[Keys.autoNext] ?: defaults.autoNext,
            concurrency = this[Keys.concurrency] ?: defaults.concurrency,
            storage = choice<StorageTarget>(Keys.storage) ?: defaults.storage,
            cleanupDays = this[Keys.cleanupDays] ?: defaults.cleanupDays,
            mangaMode = choice<ImageMode>(Keys.mangaMode) ?: old?.takeIf { it != ImageMode.PAGED_LTR } ?: defaults.mangaMode,
            comicsMode = choice<ImageMode>(Keys.comicsMode) ?: old ?: defaults.comicsMode,
            booksMode = choice<ImageMode>(Keys.booksMode) ?: old ?: defaults.booksMode,
            fit = choice<PageFit>(Keys.fit) ?: defaults.fit,
            spreads = this[Keys.spreads] ?: defaults.spreads,
            coverAlone = this[Keys.coverAlone] ?: defaults.coverAlone,
            splitWide = this[Keys.splitWide] ?: defaults.splitWide,
            tapLayout = choice<TapLayout>(Keys.tapLayout) ?: defaults.tapLayout,
            filter = choice<PageFilter>(Keys.filter) ?: defaults.filter,
            trim = this[Keys.trim] ?: defaults.trim,
            keepScreenOn = this[Keys.keepScreenOn] ?: defaults.keepScreenOn,
            brightness = this[Keys.brightness] ?: defaults.brightness,
            pureBlack = this[Keys.pureBlack] ?: defaults.pureBlack,
            theme = choice<ThemeChoice>(Keys.theme) ?: defaults.theme,
            accent = choice<Accent>(Keys.accent)?.let { if (it == Accent.AMBER && (this[Keys.look] ?: 0) < LOOK) defaults.accent else it }
                ?: defaults.accent,
            density = choice<CardDensity>(Keys.density) ?: defaults.density,
            epubTheme = choice<EpubTheme>(Keys.epubTheme) ?: defaults.epubTheme,
            epubFont = choice<EpubFont>(Keys.epubFont) ?: defaults.epubFont,
            epubSize = this[Keys.epubSize] ?: defaults.epubSize,
            epubSpacing = choice<EpubSpacing>(Keys.epubSpacing) ?: defaults.epubSpacing,
            epubMargins = choice<EpubMargins>(Keys.epubMargins) ?: defaults.epubMargins,
            epubScroll = this[Keys.epubScroll] ?: defaults.epubScroll,
            epubJustify = this[Keys.epubJustify] ?: defaults.epubJustify,
            epubColumns = choice<EpubColumns>(Keys.epubColumns) ?: defaults.epubColumns,
        )
    }

    suspend fun update(change: (AppSettings) -> AppSettings) {
        context.settingsData.edit {
            val next = change(it.settings())
            it[Keys.wifiOnly] = next.wifiOnly
            it[Keys.autoNext] = next.autoNext.coerceIn(0, 10)
            it[Keys.concurrency] = next.concurrency.coerceIn(1, 4)
            it[Keys.storage] = next.storage.name
            it[Keys.cleanupDays] = next.cleanupDays.coerceIn(0, 365)
            it[Keys.mangaMode] = next.mangaMode.name
            it[Keys.comicsMode] = next.comicsMode.name
            it[Keys.booksMode] = next.booksMode.name
            it[Keys.fit] = next.fit.name
            it[Keys.spreads] = next.spreads
            it[Keys.coverAlone] = next.coverAlone
            it[Keys.splitWide] = next.splitWide
            it[Keys.tapLayout] = next.tapLayout.name
            it[Keys.filter] = next.filter.name
            it[Keys.trim] = next.trim
            it[Keys.keepScreenOn] = next.keepScreenOn
            it[Keys.brightness] = next.brightness.coerceIn(-1f, 1f)
            it[Keys.pureBlack] = next.pureBlack
            it[Keys.theme] = next.theme.name
            it[Keys.accent] = next.accent.name
            it[Keys.look] = LOOK
            it[Keys.density] = next.density.name
            it[Keys.epubTheme] = next.epubTheme.name
            it[Keys.epubFont] = next.epubFont.name
            it[Keys.epubSize] = next.epubSize.coerceIn(0.6f, 2.5f)
            it[Keys.epubSpacing] = next.epubSpacing.name
            it[Keys.epubMargins] = next.epubMargins.name
            it[Keys.epubScroll] = next.epubScroll
            it[Keys.epubJustify] = next.epubJustify
            it[Keys.epubColumns] = next.epubColumns.name
        }
    }
}
