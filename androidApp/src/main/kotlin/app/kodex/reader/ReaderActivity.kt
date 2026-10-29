package app.kodex.reader

import android.content.Context
import android.content.Intent
import android.os.Bundle
import android.view.WindowManager
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalWindowInfo
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import androidx.core.view.WindowInsetsControllerCompat
import androidx.fragment.app.FragmentActivity
import app.kodex.AppScope
import app.kodex.R
import app.kodex.data.AppSettings
import app.kodex.data.Bookmarks
import app.kodex.data.Positions
import app.kodex.data.SettingsStore
import app.kodex.data.db.BookEntity
import app.kodex.data.db.ProgressEntity
import app.kodex.data.db.KodexDatabase
import app.kodex.download.Downloads
import app.kodex.reader.epub.EpubLinks
import app.kodex.reader.epub.EpubReader
import app.kodex.reader.image.ImageReader
import app.kodex.reader.image.NextBook
import app.kodex.reader.pdf.PdfReader
import app.kodex.sync.SyncWorker
import app.kodex.ui.theme.KodexTheme
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch
import org.koin.android.ext.android.inject
import org.readium.r2.navigator.epub.EpubNavigatorFragment

/**
 * The readers: images (comics and manga), EPUB (Readium) and PDF (androidx.pdf), full screen.
 * A FragmentActivity because Readium's EPUB navigator is a fragment; its factory has to be in
 * place before the activity restores it after a rotation.
 */
class ReaderActivity : FragmentActivity() {
    private val books: OpenBooks by inject()
    private val db: KodexDatabase by inject()
    private val settings: SettingsStore by inject()
    private val positions: Positions by inject()
    private val downloads: Downloads by inject()
    private val scope: AppScope by inject()
    private val bookmarks: Bookmarks by inject()
    private lateinit var reporter: ProgressReporter
    private var bookId = -1

    /** The reader was opened at a bookmark and has been there: after a rotation it stays where it is. */
    private var jumped = false

    override fun onCreate(savedInstanceState: Bundle?) {
        bookId = intent.getIntExtra(EXTRA_BOOK, -1)
        jumped = savedInstanceState?.getBoolean(JUMPED) == true
        val epub = books.epub?.takeIf { it.bookId == bookId }
        supportFragmentManager.fragmentFactory =
            epub?.navigatorFactory?.createFragmentFactory(epub.initialLocator, listener = EpubLinks(this))
                ?: EpubNavigatorFragment.createDummyFactory()
        super.onCreate(savedInstanceState)
        if (epub == null && supportFragmentManager.fragments.isNotEmpty()) {
            // Restored after the process was killed: the book is opened again, then shown.
            supportFragmentManager.beginTransaction().apply { supportFragmentManager.fragments.forEach { remove(it) } }.commitNow()
        }
        reporter = ProgressReporter(applicationContext, bookId, positions, downloads, scope)
        enableEdgeToEdge()
        immersive(true)
        setContent {
            val prefs by settings.settings.collectAsState(initial = AppSettings())
            KodexTheme(prefs.theme, prefs.accent) {
                LaunchedEffect(prefs.keepScreenOn) {
                    if (prefs.keepScreenOn) window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
                    else window.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
                }
                LaunchedEffect(prefs.brightness) { brightness(prefs.brightness) }
                Reader(bookId, prefs)
            }
        }
    }

    /** The window's brightness, 0–1; below 0 the device's own. */
    private fun brightness(value: Float) {
        window.attributes = window.attributes.also {
            it.screenBrightness = if (value < 0) WindowManager.LayoutParams.BRIGHTNESS_OVERRIDE_NONE else value.coerceIn(0.02f, 1f)
        }
    }

    /** A bookmark's place, when the reader was opened at one ("Läs från bokmärket"). */
    private fun jump(): ProgressEntity? {
        if (jumped) return null
        val position = intent.getStringExtra(EXTRA_POSITION) ?: return null
        return ProgressEntity(bookId, position, intent.getStringExtra(EXTRA_KIND), 0.0, false, null, "", null)
    }

    /** The book, how it opened, and where its reader starts. */
    private class Open(
        val book: BookEntity,
        val opened: Opened,
        val start: ProgressEntity?,
        val next: NextBook?,
        val libraryType: String?,
        val seriesTitle: String?,
    )

    @Composable
    private fun Reader(bookId: Int, prefs: AppSettings) {
        val width = LocalWindowInfo.current.containerSize.width
        var open by remember { mutableStateOf<Open?>(null) }
        LaunchedEffect(bookId) {
            val book = db.catalog().bookNow(bookId)
            if (book == null) {
                finish()
                return@LaunchedEffect
            }
            val jump = jump()
            val opened = books.open(book, width, prefs.trim, jump)
            if (opened is Opened.Epub) {
                // The navigator's factory for this book, before the navigator is shown (the
                // first time, or after the process was killed).
                supportFragmentManager.fragmentFactory = opened.session.navigatorFactory
                    .createFragmentFactory(opened.session.initialLocator, listener = EpubLinks(this@ReaderActivity))
            }
            val next = db.catalog().nextInSeries(bookId)?.let { NextBook(it.id, it.title) }
            val seriesTitle = book.seriesId?.let { db.catalog().series(it).first()?.title }
            open = Open(book, opened, jump ?: db.catalog().progressNow(bookId), next, db.catalog().libraryTypeOf(bookId), seriesTitle)
        }
        val marks by remember(bookId) { bookmarks.of(bookId) }.collectAsState(initial = emptyList())
        Box(Modifier.fillMaxSize().background(if (prefs.pureBlack) Color.Black else KodexTheme.colors.background)) {
            val current = open
            if (current == null) {
                CircularProgressIndicator(Modifier.align(Alignment.Center))
                return@Box
            }
            val host = ReaderHost(
                title = ReaderTitle(current.book.title, current.seriesTitle),
                mode = prefs.modeFor(current.libraryType),
                bookmarks = marks,
                addBookmark = { at ->
                    scope.launch {
                        bookmarks.add(bookId, at)
                        SyncWorker.sendPositions(applicationContext)
                    }
                },
                removeBookmark = { id ->
                    scope.launch {
                        bookmarks.remove(id)
                        SyncWorker.sendPositions(applicationContext)
                    }
                },
                light = LightControls(
                    brightness = prefs.brightness,
                    pureBlack = prefs.pureBlack,
                    onBrightness = ::brightness,
                    onBrightnessDone = { level -> scope.launch { settings.update { it.copy(brightness = level) } } },
                    onPureBlack = { on -> scope.launch { settings.update { it.copy(pureBlack = on) } } },
                ),
                update = { change -> scope.launch { settings.update(change) } },
            )
            CompositionLocalProvider(LocalReaderInk provides if (prefs.pureBlack) Color.White else KodexTheme.colors.text) {
            when (val opened = current.opened) {
                is Opened.Images -> ImageReader(
                    current.book, opened.pages, prefs, current.start, current.next, host,
                    onPosition = reporter::report,
                    onChrome = ::chrome,
                    onNext = ::openNext,
                    onClose = ::finish,
                )
                is Opened.Epub -> EpubReader(current.book, opened.session, host, reporter::report, ::chrome, ::finish)
                is Opened.Pdf -> PdfReader(current.book, opened.file, current.start, host, reporter::report, ::chrome, ::finish)
                Opened.NeedsDownload -> Problem(stringResource(R.string.reader_needs_download))
                is Opened.Failed -> Problem(stringResource(R.string.reader_failed, opened.message))
            }
            }
        }
    }

    @Composable
    private fun Problem(message: String) {
        Column(
            Modifier.fillMaxSize().padding(32.dp).testTag("reader-problem"),
            verticalArrangement = Arrangement.spacedBy(16.dp, Alignment.CenterVertically),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Text(message, color = LocalReaderInk.current, textAlign = TextAlign.Center, style = MaterialTheme.typography.bodyLarge)
            Button(onClick = ::finish) { Text(stringResource(R.string.back)) }
        }
    }

    /** The next book in the series, in a reader of its own. */
    private fun openNext(bookId: Int) {
        reporter.flush()
        startActivity(ReaderActivity.intent(this, bookId))
        finish()
    }

    /** The reader's bars are shown: the system's come with them. */
    private fun chrome(shown: Boolean) = immersive(!shown)

    private fun immersive(on: Boolean) {
        WindowCompat.getInsetsController(window, window.decorView).apply {
            systemBarsBehavior = WindowInsetsControllerCompat.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE
            if (on) hide(WindowInsetsCompat.Type.systemBars()) else show(WindowInsetsCompat.Type.systemBars())
        }
    }

    override fun onSaveInstanceState(outState: Bundle) {
        super.onSaveInstanceState(outState)
        outState.putBoolean(JUMPED, true)
    }

    override fun onStop() {
        super.onStop()
        reporter.flush()
    }

    override fun onDestroy() {
        super.onDestroy()
        if (isFinishing) books.close(bookId)
    }

    companion object {
        private const val EXTRA_BOOK = "book_id"
        private const val EXTRA_POSITION = "position"
        private const val EXTRA_KIND = "locator_kind"
        private const val JUMPED = "jumped"

        /** The reader for [bookId], at its position, or at [position] (of [kind]: a bookmark's). */
        fun intent(context: Context, bookId: Int, position: String? = null, kind: String? = null): Intent =
            Intent(context, ReaderActivity::class.java).putExtra(EXTRA_BOOK, bookId).apply {
                if (position != null) {
                    putExtra(EXTRA_POSITION, position)
                    putExtra(EXTRA_KIND, kind)
                }
            }
    }
}

