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
import app.kodex.ui.theme.KodexTheme
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
    private lateinit var reporter: ProgressReporter
    private var bookId = -1

    override fun onCreate(savedInstanceState: Bundle?) {
        bookId = intent.getIntExtra(EXTRA_BOOK, -1)
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
            KodexTheme(prefs.theme) {
                LaunchedEffect(prefs.keepScreenOn) {
                    if (prefs.keepScreenOn) window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
                    else window.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
                }
                Reader(bookId, prefs)
            }
        }
    }

    /** The book, how it opened, and where its reader starts. */
    private class Open(val book: BookEntity, val opened: Opened, val start: ProgressEntity?, val next: NextBook?)

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
            val opened = books.open(book, width, prefs.trim)
            if (opened is Opened.Epub) {
                // The navigator's factory for this book, before the navigator is shown (the
                // first time, or after the process was killed).
                supportFragmentManager.fragmentFactory = opened.session.navigatorFactory
                    .createFragmentFactory(opened.session.initialLocator, listener = EpubLinks(this@ReaderActivity))
            }
            val next = db.catalog().nextInSeries(bookId)?.let { NextBook(it.id, it.title) }
            open = Open(book, opened, db.catalog().progressNow(bookId), next)
        }
        Box(Modifier.fillMaxSize().background(Color.Black)) {
            val current = open
            if (current == null) {
                CircularProgressIndicator(Modifier.align(Alignment.Center))
                return@Box
            }
            when (val opened = current.opened) {
                is Opened.Images -> ImageReader(
                    current.book, opened.pages, prefs, current.start, current.next,
                    onPosition = reporter::report,
                    onChrome = ::chrome,
                    onNext = ::openNext,
                    onClose = ::finish,
                )
                is Opened.Epub -> EpubReader(current.book, opened.session, reporter::report, ::chrome, ::finish)
                is Opened.Pdf -> PdfReader(current.book, opened.file, current.start, reporter::report, ::chrome, ::finish)
                Opened.NeedsDownload -> Problem(stringResource(R.string.reader_needs_download))
                is Opened.Failed -> Problem(stringResource(R.string.reader_failed, opened.message))
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
            Text(message, color = Color.White, textAlign = TextAlign.Center, style = MaterialTheme.typography.bodyLarge)
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

        fun intent(context: Context, bookId: Int): Intent =
            Intent(context, ReaderActivity::class.java).putExtra(EXTRA_BOOK, bookId)
    }
}

