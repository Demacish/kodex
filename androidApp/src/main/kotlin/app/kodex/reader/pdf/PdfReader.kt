package app.kodex.reader.pdf

import android.net.Uri
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.runtime.snapshotFlow
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawing
import androidx.compose.foundation.layout.windowInsetsPadding
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Menu
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.ui.unit.dp
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.pdf.ExperimentalPdfApi
import androidx.pdf.PdfDocument
import androidx.pdf.SandboxedPdfLoader
import androidx.pdf.compose.PdfViewer
import androidx.pdf.compose.rememberPdfViewerState
import app.kodex.R
import app.kodex.data.Position
import app.kodex.data.db.BookEntity
import app.kodex.data.db.ProgressEntity
import app.kodex.reader.ReaderChrome
import app.kodex.reader.ReaderHost
import app.kodex.ui.theme.KodexTheme
import app.kodex.shared.reader.PagePosition
import java.io.File
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.drop
import kotlinx.coroutines.launch

/**
 * PDF with androidx.pdf (the platform's PDF renderer in a sandboxed service): scrolling
 * pages, pinch to zoom, text selection. The position is the server's "pdf" kind, the 1-based
 * page number.
 */
@OptIn(ExperimentalPdfApi::class)
@Composable
fun PdfReader(
    book: BookEntity,
    file: File,
    start: ProgressEntity?,
    host: ReaderHost,
    onPosition: (Position) -> Unit,
    onChrome: (Boolean) -> Unit,
    onClose: () -> Unit,
) {
    val context = LocalContext.current
    var document by remember { mutableStateOf<PdfDocument?>(null) }
    var failed by remember { mutableStateOf<String?>(null) }
    var chrome by rememberSaveable { mutableStateOf(false) }
    val state = rememberPdfViewerState()
    val scope = rememberCoroutineScope()
    LaunchedEffect(chrome) { onChrome(chrome) }
    LaunchedEffect(file) {
        runCatching { SandboxedPdfLoader(context).openDocument(Uri.fromFile(file)) }
            .onSuccess { document = it }
            .onFailure { failed = it.message ?: it.javaClass.simpleName }
    }
    DisposableEffect(Unit) { onDispose { document?.close() } }

    Box(Modifier.fillMaxSize().testTag("pdf-reader")) {
        val opened = document
        when {
            failed != null -> Text(
                stringResource(R.string.reader_failed, failed.orEmpty()),
                color = KodexTheme.colors.text,
                modifier = Modifier.align(Alignment.Center),
            )
            opened == null -> CircularProgressIndicator(Modifier.align(Alignment.Center))
            else -> {
                val count = opened.pageCount
                LaunchedEffect(opened) {
                    val first = PagePosition.from(start?.locatorKind, start?.position, start?.percent ?: 0.0, count)
                    if (first > 0) state.scrollToPage(first)
                    snapshotFlow { state.firstVisiblePage }.distinctUntilChanged().drop(1).collect { page ->
                        val last = (page + state.visiblePagesCount - 1).coerceIn(page, count - 1)
                        onPosition(Position((page + 1).toString(), "pdf", (last + 1) * 100.0 / count, last >= count - 1))
                    }
                }
                PdfViewer(pdfDocument = opened, state = state, modifier = Modifier.fillMaxSize())
                // The PDF view takes every touch for scrolling, zooming and selecting, so the
                // menu has a button of its own.
                if (!chrome) {
                    IconButton(
                        onClick = { chrome = true },
                        modifier = Modifier.align(Alignment.TopEnd).windowInsetsPadding(WindowInsets.safeDrawing).padding(8.dp)
                            .background(Color(0x99000000), CircleShape),
                    ) {
                        Icon(Icons.Filled.Menu, contentDescription = stringResource(R.string.reader_menu), tint = Color.White)
                    }
                }
                if (chrome) {
                    val first = state.firstVisiblePage
                    ReaderChrome(
                        title = host.title,
                        page = first,
                        count = count,
                        mode = null,
                        onMode = {},
                        fit = null,
                        onFit = {},
                        bookmarks = host.bookmarkControls(
                            here = { it.locatorKind == "pdf" && it.position.toIntOrNull() == first + 1 },
                            at = { Position((first + 1).toString(), "pdf", (first + 1) * 100.0 / count, false) },
                            open = { mark -> mark.position.toIntOrNull()?.let { n -> scope.launch { state.scrollToPage((n - 1).coerceIn(0, count - 1)) } } },
                        ),
                        light = host.light,
                        onSeek = { scope.launch { state.scrollToPage(it) } },
                        onClose = onClose,
                        extra = {
                            IconButton(onClick = { chrome = false }) {
                                Icon(Icons.Filled.Menu, contentDescription = stringResource(R.string.reader_menu), tint = KodexTheme.colors.text)
                            }
                        },
                    )
                }
            }
        }
    }
}
