package app.kodex.screens

import android.app.Application
import android.graphics.Bitmap
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.VerticalDivider
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.asAndroidBitmap
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.graphics.painter.Painter
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.test.captureToImage
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onRoot
import androidx.test.ext.junit.runners.AndroidJUnit4
import app.kodex.account.Session
import app.kodex.data.Accent
import app.kodex.data.AppSettings
import app.kodex.data.ImageMode
import app.kodex.data.PageFit
import app.kodex.data.ThemeChoice
import app.kodex.data.db.BookEntity
import app.kodex.data.db.BookRow
import app.kodex.data.db.BookmarkEntity
import app.kodex.data.db.CatalogCounts
import app.kodex.data.db.CollectionEntity
import app.kodex.data.db.ContinueRow
import app.kodex.data.db.DownloadEntity
import app.kodex.data.db.DownloadKinds
import app.kodex.data.db.DownloadRow
import app.kodex.data.db.DownloadState
import app.kodex.data.db.LibraryRow
import app.kodex.data.db.ProgressEntity
import app.kodex.data.db.SeriesEntity
import app.kodex.data.db.SeriesRow
import app.kodex.reader.BookmarkControls
import app.kodex.reader.LightControls
import app.kodex.reader.ReaderChrome
import app.kodex.reader.ReaderTitle
import app.kodex.shared.api.Recommendation
import app.kodex.shared.api.ReleaseEvent
import app.kodex.sync.SyncStatus
import app.kodex.ui.LocalSession
import app.kodex.ui.ShellFrame
import app.kodex.ui.Tab
import app.kodex.ui.components.LocalCoverArt
import app.kodex.ui.discover.DiscoverActions
import app.kodex.ui.discover.DiscoverContent
import app.kodex.ui.discover.DiscoverRemote
import app.kodex.ui.downloads.DownloadsActions
import app.kodex.ui.downloads.DownloadsContent
import app.kodex.ui.downloads.DownloadsTab
import app.kodex.ui.downloads.NetworkState
import app.kodex.ui.downloads.Transfer
import app.kodex.ui.library.BookActions
import app.kodex.ui.library.BookContent
import app.kodex.ui.library.LibraryHomeActions
import app.kodex.ui.library.LibraryHomeContent
import app.kodex.ui.library.LibraryHomeState
import app.kodex.ui.library.SeriesActions
import app.kodex.ui.library.SeriesContent
import app.kodex.ui.library.SeriesUiState
import app.kodex.ui.settings.SettingsActions
import app.kodex.ui.settings.SettingsContent
import app.kodex.ui.settings.SettingsInfo
import app.kodex.ui.theme.KodexTheme
import java.io.File
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.annotation.Config
import org.robolectric.annotation.GraphicsMode

/**
 * Pictures of the app's screens with made-up books, drawn by Robolectric at a phone's size and
 * at a 12.4- and a 10-inch tablet's, in both orientations (phase 8): CI uploads them as the
 * "app-screenshots" artifact, to look at and compare. Each device is a subclass.
 */
abstract class Screens(private val device: String, private val theme: ThemeChoice = ThemeChoice.DARK, private val wide: Boolean = false) {
    @get:Rule val compose = createComposeRule()

    private fun shoot(name: String, tab: Tab?, content: @Composable () -> Unit) {
        compose.setContent {
            KodexTheme(theme, Accent.AMBER) {
                CompositionLocalProvider(LocalSession provides SESSION, LocalCoverArt provides { id -> Art(id) }) {
                    if (tab != null) ShellFrame(tab, {}, badge = { it == Tab.DOWNLOADS }) { content() } else content()
                }
            }
        }
        compose.waitForIdle()
        val bitmap = compose.onRoot().captureToImage().asAndroidBitmap()
        val dir = File(System.getProperty("kodex.screenshots") ?: "build/outputs/screenshots", device).apply { mkdirs() }
        File(dir, "$name.png").outputStream().use { bitmap.compress(Bitmap.CompressFormat.PNG, 100, it) }
    }

    @Test fun library() = shoot("01-library", Tab.LIBRARY) {
        LibraryHomeContent(
            LibraryHomeState(libraries = LIBRARIES, reading = READING, recent = RECENT, collections = COLLECTIONS, downloaded = DOWNLOADED,
                synced = "Synkad 29 okt. 2026 22:29 · 2 positioner väntar på att skickas"),
            SETTINGS, LibraryHomeActions(), empty = {},
        )
    }

    @Test fun oneLibrary() = shoot("02-library-manga", Tab.LIBRARY) {
        LibraryHomeContent(
            LibraryHomeState(libraries = LIBRARIES, selected = 2, series = MANGA, loose = RECENT.take(2), downloaded = DOWNLOADED, filtersOpen = true),
            SETTINGS, LibraryHomeActions(), empty = {},
        )
    }

    @Test fun series() = shoot("03-series", Tab.LIBRARY) {
        SeriesContent(SERIES, MANGA.first(), CHAPTERS, SETTINGS, SeriesUiState(), SeriesActions())
    }

    @Test fun seriesChoosing() = shoot("04-series-choosing", Tab.LIBRARY) {
        SeriesContent(SERIES, MANGA.first(), CHAPTERS, SETTINGS, SeriesUiState(selecting = true, selected = setOf(103, 104, 105)), SeriesActions())
    }

    @Test fun book() = shoot("05-book", Tab.LIBRARY) { Book() }

    /** On a wide screen a series and a book sit side by side (the list-detail layout). */
    @Test fun seriesAndBook() {
        if (!wide) return
        shoot("06-series-and-book", Tab.LIBRARY) {
            Row(Modifier.fillMaxSize()) {
                Box(Modifier.weight(1f)) { SeriesContent(SERIES, MANGA.first(), CHAPTERS, SETTINGS, SeriesUiState(), SeriesActions()) }
                VerticalDivider()
                Box(Modifier.weight(1f)) { Book() }
            }
        }
    }

    @Test fun downloadsActive() = shoot("07-downloads-active", Tab.DOWNLOADS) { Downloads(DownloadsTab.ACTIVE) }

    @Test fun downloadsQueue() = shoot("08-downloads-queue", Tab.DOWNLOADS) { Downloads(DownloadsTab.QUEUE) }

    @Test fun downloadsHistory() = shoot("09-downloads-history", Tab.DOWNLOADS) { Downloads(DownloadsTab.HISTORY) }

    @Test fun discover() = shoot("10-discover", Tab.DISCOVER) {
        DiscoverContent(MANGA.filter { it.following }, DiscoverRemote(releases = RELEASES, recommendations = SUGGESTIONS), SETTINGS, DiscoverActions())
    }

    @Test fun settings() = shoot("11-settings", Tab.SETTINGS) {
        SettingsContent(
            SETTINGS,
            SettingsInfo(
                username = "anna", server = SESSION.server, syncedAt = 1_793_310_540_000L, pending = 2, status = SyncStatus(),
                counts = CatalogCounts(3, 128, 2_048), cardAvailable = true, freeInternal = 38_200_000_000L, freeCard = 120_400_000_000L,
                cacheBytes = 1_400_000_000L,
            ),
            SettingsActions(),
        )
    }

    @Test fun reader() = shoot("12-reader", null) {
        Box(Modifier.fillMaxSize().background(Color.Black)) {
            Image(Art(7), contentDescription = null, contentScale = ContentScale.Crop,
                modifier = Modifier.fillMaxHeight().aspectRatio(2f / 3f).align(Alignment.Center))
            ReaderChrome(
                title = ReaderTitle("Kapitel 43: Solkatten", "Månfiskarna", rtl = true),
                page = 11, count = 38,
                mode = ImageMode.PAGED_RTL, onMode = {},
                fit = PageFit.PAGE, onFit = {},
                bookmarks = BookmarkControls(true, MARKS, {}, {}, {}),
                light = LightControls(0.75f, true, {}, {}, {}),
                onSeek = {}, onClose = {},
            )
        }
    }

    @Composable
    private fun Book() = BookContent(
        BookEntity(104, 2, 20, "Kapitel 43: Solkatten", "043", 43.0, "cbz", 32_100_000, 38, "issue", "Ren Moriyama",
            "Kaptenen hittar en karta som inte borde finnas, och månen lyser åt fel håll.", 2024, "sv",
            filePath = "/library/manga/Månfiskarna/Månfiskarna 043.cbz", genres = "Äventyr, Fantasy, Hav"),
        CHAPTERS.first { it.id == 104 },
        ProgressEntity(104, "17", "page", 47.0, false, null, "2026-10-29T20:15:00Z", "Pixel"),
        DownloadEntity(104, DownloadState.DONE, DownloadKinds.FILE, 32_100_000, 32_100_000, "9f2c4e1a7b3d5f60c8e2a1b4d6f8091a2b3c4d5e6f708192a3b4c5d6e7f80910",
            null, false, 0, null, finishedAt = 1_793_300_000_000L),
        MARKS,
        "/storage/emulated/0/Android/data/app.kodex/files/books/104",
        SETTINGS,
        BookActions(),
    )

    @Composable
    private fun Downloads(tab: DownloadsTab) = DownloadsContent(TRANSFERS, NetworkState(), 38_200_000_000L, 3_200_000_000L, SETTINGS, tab, DownloadsActions())
}

private val SESSION = Session("https://kodex.example", "kdx_test", "anna", "device", "Pixel")

private val SETTINGS = AppSettings()

private val LIBRARIES = listOf(
    LibraryRow(1, "Serier", "comics", 41, 612),
    LibraryRow(2, "Manga", "manga", 23, 1_204),
    LibraryRow(3, "Böcker", "ebooks", 12, 232),
)

private val COLLECTIONS = listOf(CollectionEntity(1, "Sommarläsning", "manual"), CollectionEntity(2, "Klassiker", "manual"),
    CollectionEntity(3, "Läs härnäst", "smart"))

private fun book(
    id: Int,
    title: String,
    series: String?,
    number: Double?,
    libraryType: String,
    format: String = "cbz",
    percent: Double? = null,
    finished: Boolean? = null,
    download: DownloadState? = null,
    edition: String = "issue",
    seriesId: Int? = 10,
    pages: Int = 36,
    authors: String = "",
) = BookRow(
    id, seriesId, 1, title, number, format, 34_500_000L, pages, edition, authors, series, libraryType, percent, finished, download,
    if (download == DownloadState.RUNNING) 21_000_000L else if (download == DownloadState.DONE) 34_500_000L else null,
    if (download != null) 34_500_000L else null,
)

private val READING = listOf(
    ContinueRow(104, "Kapitel 43: Solkatten", 20, "Månfiskarna", 43.0, "cbz", 38, "manga", 47.0, "2026-10-29T20:15:00Z", DownloadState.DONE),
    ContinueRow(201, "Den sista fyren", null, null, null, "epub", 480, "ebooks", 44.0, "2026-10-28T19:00:00Z", null),
    ContinueRow(301, "Järnlotsen #14", 30, "Järnlotsen", 14.0, "cbz", 24, "comics", 88.0, "2026-10-27T18:00:00Z", DownloadState.DONE),
    ContinueRow(401, "Glasfjällen 8", 40, "Glasfjällen", 8.0, "cbz", 30, "manga", 20.0, "2026-10-26T18:00:00Z", null),
)

private val RECENT = listOf(
    book(501, "Ekot från Ödemark", "Ekot från Ödemark", 4.0, "manga", edition = "collected", download = DownloadState.DONE),
    book(502, "Kartritarens dotter", null, null, "ebooks", format = "epub", percent = 65.0, seriesId = null, authors = "Elin Varg"),
    book(503, "Kvicksilverstaden #7", "Kvicksilverstaden", 7.0, "comics", download = DownloadState.DONE),
    book(504, "Tidvattnet", null, null, "ebooks", format = "epub", seriesId = null, authors = "Jonas Ek"),
    book(505, "Sju sorters regn 12", "Sju sorters regn", 12.0, "manga", download = DownloadState.RUNNING),
    book(506, "Nattväktaren #3", "Nattväktaren", 3.0, "comics", finished = true, percent = 100.0),
    book(507, "Silverrävens väg", "Silverrävens väg", 1.0, "manga"),
    book(508, "Stjärnhavet #22", "Stjärnhavet", 22.0, "comics", download = DownloadState.DONE),
    book(509, "Vinterbiblioteket", null, null, "ebooks", format = "pdf", seriesId = null),
)

private val DOWNLOADED = RECENT.filter { it.downloadState == DownloadState.DONE }

private val MANGA = listOf(
    SeriesRow(20, 2, "Månfiskarna", 2019, true, "manga", 128, 42, 1, 24, 101, 230, "2026-10-29T20:15:00Z"),
    SeriesRow(21, 2, "Glasfjällen", 2021, true, "manga", 30, 7, 1, 0, 111, 240, "2026-10-26T18:00:00Z"),
    SeriesRow(22, 2, "Ekot från Ödemark", 2016, false, "manga", 12, 12, 0, 12, 121, 250, "2026-09-02T18:00:00Z"),
    SeriesRow(23, 2, "Sju sorters regn", 2022, true, "manga", 18, 0, 0, 1, 131, 260, null),
    SeriesRow(24, 2, "Silverrävens väg", 2023, false, "manga", 9, 0, 0, 0, 141, 270, null),
    SeriesRow(25, 2, "Kvällsljus över Haga", 2018, false, "manga", 21, 3, 0, 0, 151, 280, "2026-08-01T18:00:00Z"),
    SeriesRow(26, 2, "Pappersdraken", 2020, false, "manga", 14, 14, 0, 0, 161, 290, "2026-05-01T18:00:00Z"),
)

private val SERIES = SeriesEntity(
    20, 2, "Månfiskarna", 2019, "Nordlys förlag",
    "Ombord på trålaren Ellida fiskar besättningen upp något som lyser i nätet varje fullmåne. När kaptenens dotter hittar en karta " +
        "över ett hav som inte finns på någon annan karta börjar resan som ingen av dem kommer tillbaka ifrån.",
    128, following = true, status = "ongoing",
)

private val CHAPTERS = listOf(
    book(101, "Kapitel 40: Isen sjunger", "Månfiskarna", 40.0, "manga", finished = true, percent = 100.0, download = DownloadState.DONE, seriesId = 20),
    book(102, "Kapitel 41: Lyktorna", "Månfiskarna", 41.0, "manga", finished = true, percent = 100.0, download = DownloadState.DONE, seriesId = 20),
    book(103, "Kapitel 42: Vrakgodset", "Månfiskarna", 42.0, "manga", finished = true, percent = 100.0, download = DownloadState.DONE, seriesId = 20),
    book(104, "Kapitel 43: Solkatten", "Månfiskarna", 43.0, "manga", percent = 47.0, download = DownloadState.DONE, seriesId = 20, pages = 38),
    book(105, "Kapitel 44: Det yttre skäret", "Månfiskarna", 44.0, "manga", download = DownloadState.RUNNING, seriesId = 20),
    book(106, "Kapitel 45: Fyrvaktaren", "Månfiskarna", 45.0, "manga", download = DownloadState.QUEUED, seriesId = 20),
    book(107, "Kapitel 46: Mörkt vatten", "Månfiskarna", 46.0, "manga", seriesId = 20),
    book(108, "Kapitel 47: Nordvästpassagen", "Månfiskarna", 47.0, "manga", seriesId = 20),
    book(109, "Volym 1", "Månfiskarna", 1.0, "manga", edition = "collected", finished = true, percent = 100.0, seriesId = 20),
    book(110, "Volym 2", "Månfiskarna", 2.0, "manga", edition = "collected", seriesId = 20),
)

private val MARKS = listOf(
    BookmarkEntity("a1", 104, "11", "page", 31.0, null, null, "2026-10-29T20:10:00Z", null),
    BookmarkEntity("a2", 104, "17", "page", 47.0, null, null, "2026-10-29T20:14:00Z", null),
)

private fun download(
    id: Int,
    title: String,
    state: DownloadState,
    bytes: Long,
    total: Long,
    position: Long,
    series: String? = null,
    number: Double? = null,
    libraryType: String = "manga",
    error: String? = null,
    attempts: Int = 0,
    format: String = "cbz",
) = DownloadRow(id, state, DownloadKinds.FILE, bytes, total, null, error, false, 1_793_300_000_000L + id, null, position, attempts,
    if (state == DownloadState.DONE) 1_793_300_000_000L - id * 86_400_000L else null, false, title, format, number, series, libraryType)

private val TRANSFERS = listOf(
    Transfer(download(105, "Kapitel 44: Det yttre skäret", DownloadState.RUNNING, 28_400_000, 35_800_000, 1, "Månfiskarna", 44.0), 11_200_000.0),
    Transfer(download(305, "Järnlotsen #15", DownloadState.RUNNING, 42_100_000, 78_000_000, 2, "Järnlotsen", 15.0, "comics"), 7_200_000.0),
    Transfer(download(405, "Glasfjällen 9", DownloadState.FAILED, 3_000_000, 36_000_000, 3, "Glasfjällen", 9.0,
        error = "Servern svarade 503", attempts = 3)),
    Transfer(download(106, "Kapitel 45: Fyrvaktaren", DownloadState.QUEUED, 0, 34_200_000, 4, "Månfiskarna", 45.0)),
    Transfer(download(502, "Kartritarens dotter", DownloadState.QUEUED, 0, 14_200_000, 5, libraryType = "ebooks", format = "epub")),
    Transfer(download(506, "Nattväktaren #4", DownloadState.PAUSED, 18_000_000, 45_000_000, 6, "Nattväktaren", 4.0, "comics")),
    Transfer(download(101, "Kapitel 40: Isen sjunger", DownloadState.DONE, 38_400_000, 38_400_000, 0, "Månfiskarna", 40.0)),
    Transfer(download(103, "Kapitel 42: Vrakgodset", DownloadState.DONE, 32_100_000, 32_100_000, 0, "Månfiskarna", 42.0)),
    Transfer(download(508, "Stjärnhavet #22", DownloadState.DONE, 52_000_000, 52_000_000, 0, "Stjärnhavet", 22.0, "comics")),
)

private val RELEASES = listOf(
    ReleaseEvent(1, 20, "Månfiskarna", "48", "Ankarljus", "2026-10-24", 230, "owned"),
    ReleaseEvent(2, 21, "Glasfjällen", "31", null, "2026-10-21", null, "released"),
    ReleaseEvent(3, 23, "Sju sorters regn", "19", "Hagel", "2026-11-12", null, "unreleased"),
    ReleaseEvent(4, 20, "Månfiskarna", "49", null, "2026-11-28", null, "unreleased"),
)

private val SUGGESTIONS = listOf(
    Recommendation(1, "Fyrskeppet", "Hanna Strand", "Du har läst allt i Månfiskarna; den här har samma hav och samma längtan."),
)

/** A made-up cover: a colour from the book's id, a moon, and a title bar. */
private class Art(id: Int) : Painter() {
    private val hue = (id * 47 % 360).toFloat()
    override val intrinsicSize: Size = Size.Unspecified

    override fun DrawScope.onDraw() {
        drawRect(Brush.verticalGradient(listOf(Color.hsv(hue, 0.55f, 0.62f), Color.hsv((hue + 40) % 360, 0.7f, 0.16f))))
        drawCircle(Color.hsv((hue + 180) % 360, 0.45f, 0.95f).copy(alpha = 0.6f), radius = size.width * 0.26f,
            center = Offset(size.width * 0.64f, size.height * 0.4f))
        drawRect(Color.Black.copy(alpha = 0.28f), topLeft = Offset(0f, size.height * 0.74f), size = Size(size.width, size.height * 0.26f))
        drawRect(Color.White.copy(alpha = 0.85f), topLeft = Offset(size.width * 0.1f, size.height * 0.08f), size = Size(size.width * 0.62f, size.height * 0.05f))
        drawRect(Color.White.copy(alpha = 0.5f), topLeft = Offset(size.width * 0.1f, size.height * 0.15f), size = Size(size.width * 0.4f, size.height * 0.025f))
    }
}

@RunWith(AndroidJUnit4::class)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
@Config(application = Application::class, qualifiers = "sv-w412dp-h915dp-port-xxhdpi")
class PhoneScreens : Screens("phone")

@RunWith(AndroidJUnit4::class)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
@Config(application = Application::class, qualifiers = "sv-w412dp-h915dp-port-xxhdpi")
class PhoneLightScreens : Screens("phone-light", ThemeChoice.LIGHT)

/** Samsung Galaxy Tab S10+: 2800 × 1752 pixels, 12.4 inches. */
@RunWith(AndroidJUnit4::class)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
@Config(application = Application::class, qualifiers = "sv-w1400dp-h876dp-land-xhdpi")
class TabletLandscapeScreens : Screens("tablet-landscape", wide = true)

@RunWith(AndroidJUnit4::class)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
@Config(application = Application::class, qualifiers = "sv-w876dp-h1400dp-port-xhdpi")
class TabletPortraitScreens : Screens("tablet-portrait", wide = true)

/** A 10-inch tablet, 1280 × 800 dp. */
@RunWith(AndroidJUnit4::class)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
@Config(application = Application::class, qualifiers = "sv-w1280dp-h800dp-land-mdpi")
class SmallTabletScreens : Screens("tablet-10in", wide = true)
