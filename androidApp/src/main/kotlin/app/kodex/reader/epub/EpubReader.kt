package app.kodex.reader.epub

import android.content.Context
import android.content.Intent
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.VolumeUp
import androidx.compose.material.icons.filled.Pause
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.core.net.toUri
import androidx.fragment.compose.AndroidFragment
import app.kodex.R
import app.kodex.data.Position
import app.kodex.data.db.BookEntity
import app.kodex.reader.ReaderChrome
import app.kodex.reader.ReaderHost
import kotlinx.coroutines.flow.drop
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.launch
import org.readium.navigator.media.tts.AndroidTtsNavigator
import org.readium.navigator.media.tts.TtsNavigator
import org.readium.r2.navigator.epub.EpubNavigatorFragment
import org.readium.r2.navigator.input.InputListener
import org.readium.r2.navigator.input.TapEvent
import org.readium.r2.navigator.util.DirectionalNavigationAdapter
import org.readium.r2.shared.ExperimentalReadiumApi
import org.readium.r2.shared.publication.Locator
import org.readium.r2.shared.util.AbsoluteUrl

/** Links in a book that leave it open in the browser. */
@OptIn(ExperimentalReadiumApi::class)
class EpubLinks(private val context: Context) : EpubNavigatorFragment.Listener {
    override fun onExternalLinkActivated(url: AbsoluteUrl) {
        runCatching {
            context.startActivity(Intent(Intent.ACTION_VIEW, url.toString().toUri()).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
        }
    }
}

/**
 * EPUB with Readium's navigator: pages turn with a tap at the sides or a swipe, the middle
 * shows the menu; "Läs upp" reads the book aloud from where the page is (Readium's TTS
 * navigator, with the device's text-to-speech engine).
 */
@OptIn(ExperimentalReadiumApi::class)
@Composable
fun EpubReader(
    book: BookEntity,
    session: EpubSession,
    host: ReaderHost,
    onPosition: (Position) -> Unit,
    onChrome: (Boolean) -> Unit,
    onClose: () -> Unit,
) {
    var navigator by remember { mutableStateOf<EpubNavigatorFragment?>(null) }
    var chrome by rememberSaveable { mutableStateOf(false) }
    var tts by remember { mutableStateOf<AndroidTtsNavigator?>(null) }
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    LaunchedEffect(chrome) { onChrome(chrome) }
    val locator by remember(navigator) { navigator?.currentLocator ?: MutableStateFlow<Locator?>(null) }.collectAsState()

    Box(Modifier.fillMaxSize().testTag("epub-reader")) {
        AndroidFragment<EpubNavigatorFragment>(Modifier.fillMaxSize()) { fragment ->
            if (navigator !== fragment) {
                navigator = fragment
                fragment.addInputListener(DirectionalNavigationAdapter(fragment))
                fragment.addInputListener(
                    object : InputListener {
                        override fun onTap(event: TapEvent): Boolean {
                            chrome = !chrome
                            return true
                        }
                    },
                )
            }
        }
        if (chrome) {
            val here = locator?.let { EpubSession.encode(it) }
            val herePlace = here?.position?.let { place(it) }
            ReaderChrome(
                title = host.title,
                page = 0,
                count = 0,
                mode = null,
                onMode = {},
                fit = null,
                onFit = {},
                bookmarks = host.bookmarkControls(
                    here = { mark -> herePlace != null && mark.locatorKind == "other" && place(mark.position) == herePlace },
                    at = { here ?: Position(null, null, 0.0, false) },
                    open = { mark ->
                        EpubSession.decode(session.publication, mark.locatorKind, mark.position)?.let { target ->
                            scope.launch { navigator?.go(target, animated = false) }
                        }
                    },
                ),
                light = host.light,
                onSeek = {},
                onClose = onClose,
                extra = {
                    FilterChip(
                        selected = tts != null,
                        onClick = {
                            val playing = tts
                            if (playing != null) {
                                playing.close()
                                tts = null
                            } else {
                                scope.launch {
                                    val factory = session.ttsFactory(context) ?: return@launch
                                    val start = navigator?.currentLocator?.value
                                    factory.createNavigator(
                                        object : TtsNavigator.Listener {
                                            override fun onStopRequested() {
                                                tts?.close()
                                                tts = null
                                            }
                                        },
                                        initialLocator = start,
                                    ).onSuccess {
                                        tts = it
                                        it.play()
                                    }
                                }
                            }
                        },
                        label = { Text(stringResource(if (tts != null) R.string.tts_stop else R.string.tts_start)) },
                        leadingIcon = {
                            Icon(if (tts != null) Icons.Filled.Pause else Icons.AutoMirrored.Filled.VolumeUp, contentDescription = null)
                        },
                        modifier = Modifier.testTag("tts"),
                    )
                },
            )
        }
    }

    // Where the reader is (the first one is where it opened, which isn't reading).
    val current = navigator
    LaunchedEffect(current) {
        current ?: return@LaunchedEffect
        current.currentLocator.drop(1).collect { onPosition(EpubSession.encode(it)) }
    }
    // The page follows the voice.
    val voice = tts
    LaunchedEffect(voice, current) {
        if (voice == null || current == null) return@LaunchedEffect
        voice.currentLocator.collect { current.go(it, animated = false) }
    }
    DisposableEffect(Unit) { onDispose { tts?.close() } }
}

/** A place in a chapter, to the hundredth: bookmarks this close are the same place. */
private fun place(position: String): String {
    val at = position.lastIndexOf('@')
    if (at < 0) return position
    val progression = position.substring(at + 1).toDoubleOrNull() ?: 0.0
    return position.substring(0, at) + "@" + "%.2f".format(java.util.Locale.ROOT, progression)
}
