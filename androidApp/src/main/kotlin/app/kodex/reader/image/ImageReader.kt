package app.kodex.reader.image

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.gestures.awaitEachGesture
import androidx.compose.foundation.gestures.awaitFirstDown
import androidx.compose.foundation.gestures.calculatePan
import androidx.compose.foundation.gestures.calculateZoom
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.requiredSize
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.pager.HorizontalPager
import androidx.compose.foundation.pager.rememberPagerState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowForward
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.Replay
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.key
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.runtime.snapshotFlow
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.clipToBounds
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.ColorFilter
import androidx.compose.ui.graphics.ColorMatrix
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.input.pointer.positionChanged
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.LocalWindowInfo
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import app.kodex.R
import app.kodex.data.AppSettings
import app.kodex.data.ImageMode
import app.kodex.data.PageFilter
import app.kodex.data.PageFit
import app.kodex.data.Position
import app.kodex.data.db.BookEntity
import app.kodex.data.db.ProgressEntity
import app.kodex.reader.ImagePages
import app.kodex.reader.LocalReaderInk
import app.kodex.reader.ReaderChrome
import app.kodex.reader.ReaderHost
import app.kodex.reader.ReaderTitle
import app.kodex.shared.reader.Half
import app.kodex.shared.reader.PagePosition
import app.kodex.shared.reader.PageSize
import app.kodex.shared.reader.Slot
import app.kodex.shared.reader.TapAction
import app.kodex.shared.reader.singlePages
import app.kodex.shared.reader.spreads
import app.kodex.shared.reader.stepOf
import app.kodex.shared.reader.tapAction
import app.kodex.ui.components.Cover
import app.kodex.ui.theme.KodexTheme
import coil3.compose.LocalPlatformContext
import coil3.compose.SubcomposeAsyncImage
import coil3.compose.SubcomposeAsyncImageContent
import coil3.network.httpHeaders
import coil3.request.ImageRequest
import coil3.size.Precision
import kotlinx.coroutines.launch

/**
 * Comics and manga: page by page left to right or right to left (two pages side by side on a
 * wide screen, or a wide page in halves on a narrow one), or one long strip for webtoons.
 * A page fits the screen whole, by its width or height, or at its own size. Pinch or double-tap
 * to zoom; tap the sides to turn the page (or only the edges, or not at all) and the middle for
 * the menu. The next book in the series waits after the last page.
 */
/** The book after this one in its series, offered at the end. */
data class NextBook(val id: Int, val title: String)

@Composable
fun ImageReader(
    book: BookEntity,
    pages: ImagePages,
    prefs: AppSettings,
    start: ProgressEntity?,
    next: NextBook?,
    host: ReaderHost,
    onPosition: (Position) -> Unit,
    onChrome: (Boolean) -> Unit,
    onNext: (Int) -> Unit,
    onClose: () -> Unit,
) {
    val count = pages.count
    if (count == 0) {
        Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
            Text(stringResource(R.string.reader_no_pages), color = LocalReaderInk.current)
        }
        return
    }
    val first = remember { PagePosition.from(start?.locatorKind, start?.position, start?.percent ?: 0.0, count) }
    var page by rememberSaveable { mutableIntStateOf(first) }
    var mode by rememberSaveable { mutableStateOf(host.mode) }
    var fit by rememberSaveable { mutableStateOf(prefs.fit) }
    var chrome by rememberSaveable { mutableStateOf(false) }
    LaunchedEffect(chrome) { onChrome(chrome) }

    val window = LocalWindowInfo.current.containerSize
    val wide = window.width > window.height
    val rtl = mode == ImageMode.PAGED_RTL
    // The reader's steps: two pages side by side on a wide screen, else one page (or half a
    // wide one) at a time.
    val steps = remember(count, pages.sizes, wide, prefs.spreads, prefs.coverAlone, prefs.splitWide, mode) {
        when {
            mode == ImageMode.VERTICAL -> List(count) { listOf(Slot(it)) }
            wide && prefs.spreads -> spreads(count, pages.sizes, prefs.coverAlone).map { group -> group.map { Slot(it) } }
            else -> singlePages(count, pages.sizes, split = prefs.splitWide && !wide, rtl = rtl)
        }
    }
    // Opening a book isn't reading it: only a page turn reports a position.
    var turned by rememberSaveable { mutableStateOf(false) }
    // This sitting: since when, and which pages were seen (the end's reading time and pace).
    val openedAt = remember { System.currentTimeMillis() }
    var seen by remember { mutableStateOf(emptySet<Int>()) }
    val showing: (List<Slot>) -> Unit = { step ->
        if (step.none { it.page == page }) turned = true
        page = step.first().page
        seen = seen + step.map { it.page }
        if (turned) {
            val last = step.last().page
            onPosition(Position(PagePosition(page, count).position, "page", (last + 1) * 100.0 / count, last >= count - 1))
        }
    }
    val filter = remember(prefs.filter) { colorFilter(prefs.filter) }
    val onTap: (Float) -> TapAction = { x -> tapAction(x, rtl = rtl, layout = prefs.tapLayout) }

    val end: @Composable () -> Unit = {
        EndPanel(
            title = host.title,
            count = count,
            openedAt = openedAt,
            seen = seen.size,
            next = next,
            onNext = onNext,
            onRestart = { showing(steps.first()) },
            onClose = onClose,
        )
    }
    Box(Modifier.fillMaxSize().testTag("image-reader")) {
        key(steps, mode) {
            when (mode) {
                ImageMode.VERTICAL -> Strip(
                    pages, page, filter, end,
                    onShowing = { showing(listOf(Slot(it))) },
                    onMenu = { chrome = !chrome },
                )
                else -> Paged(
                    pages, steps, page, rtl, fit, filter, end,
                    onShowing = showing,
                    onTap = onTap,
                    onMenu = { chrome = !chrome },
                )
            }
        }
        if (chrome) {
            val step = steps[stepOf(steps, page)].map { it.page }
            ReaderChrome(
                title = host.title.copy(rtl = rtl),
                page = page,
                count = count,
                mode = mode,
                onMode = { mode = it },
                fit = fit,
                onFit = { chosen ->
                    fit = chosen
                    host.update { it.copy(fit = chosen) }
                },
                bookmarks = host.bookmarkControls(
                    here = { it.locatorKind == "page" && it.position.toIntOrNull() in step },
                    at = { Position(page.toString(), "page", (step.last() + 1) * 100.0 / count, false) },
                    open = { mark -> mark.position.toIntOrNull()?.let { target -> showing(steps[stepOf(steps, target.coerceIn(0, count - 1))]) } },
                ),
                light = host.light,
                onSeek = { target -> showing(steps[stepOf(steps, target)]) },
                onClose = onClose,
            )
        }
    }
}

@Composable
private fun Paged(
    pages: ImagePages,
    steps: List<List<Slot>>,
    page: Int,
    rtl: Boolean,
    fit: PageFit,
    filter: ColorFilter?,
    end: @Composable () -> Unit,
    onShowing: (List<Slot>) -> Unit,
    onTap: (Float) -> TapAction,
    onMenu: () -> Unit,
) {
    // After the last page, the end: how the reading went, and the next book in the series.
    val total = steps.size + 1
    val state = rememberPagerState(initialPage = stepOf(steps, page)) { total }
    val scope = rememberCoroutineScope()
    LaunchedEffect(state) { snapshotFlow { state.settledPage }.collect { if (it < steps.size) onShowing(steps[it]) } }
    // A seek from the menu.
    LaunchedEffect(page) {
        val target = stepOf(steps, page)
        if (state.currentPage >= steps.size || steps[state.currentPage].none { it.page == page }) state.scrollToPage(target)
    }
    HorizontalPager(
        state = state,
        modifier = Modifier.fillMaxSize(),
        reverseLayout = rtl,
        // The pages either side are loaded before they are turned to.
        beyondViewportPageCount = 2,
        key = { if (it < steps.size) steps[it].first().let { slot -> "${slot.page}-${slot.half}" } else "end" },
    ) { index ->
        if (index >= steps.size) {
            end()
            return@HorizontalPager
        }
        val step = steps[index]
        Zoomable(
            onTap = { x ->
                when (onTap(x)) {
                    TapAction.PREVIOUS -> scope.launch { state.animateScrollToPage((state.currentPage - 1).coerceAtLeast(0)) }
                    TapAction.NEXT -> scope.launch { state.animateScrollToPage((state.currentPage + 1).coerceAtMost(total - 1)) }
                    TapAction.MENU -> onMenu()
                }
            },
        ) {
            val ordered = if (rtl) step.reversed() else step
            // Half pages are always shown whole: their halves are cut to fit the screen.
            if (fit != PageFit.PAGE && ordered.none { it.half != null }) {
                Fitted(pages, ordered, fit, filter)
                return@Zoomable
            }
            Row(Modifier.fillMaxSize(), horizontalArrangement = Arrangement.Center, verticalAlignment = Alignment.CenterVertically) {
                ordered.forEach { slot ->
                    val half = slot.half
                    val size = pages.sizes.getOrNull(slot.page)
                    if (half != null && size != null) {
                        HalfPage(pages, slot.page, half, size, filter)
                    } else {
                        Page(
                            pages, slot.page, filter,
                            Modifier.weight(1f, fill = false).fillMaxHeight(),
                            alignment = when {
                                step.size == 1 -> Alignment.Center
                                slot == ordered.first() -> Alignment.CenterEnd
                                else -> Alignment.CenterStart
                            },
                        )
                    }
                }
            }
        }
    }
}

/**
 * A step's pages fitted to the screen's width (scrolling down a tall page), its height
 * (scrolling across a wide one), or at one image pixel per screen pixel (scrolling both ways).
 */
@Composable
private fun Fitted(pages: ImagePages, ordered: List<Slot>, fit: PageFit, filter: ColorFilter?) {
    val density = LocalDensity.current
    when (fit) {
        PageFit.WIDTH -> Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState())) {
            Row(Modifier.fillMaxWidth()) {
                ordered.forEach { slot ->
                    val size = pages.sizes.getOrNull(slot.page)
                    val shape = if (size != null) Modifier.aspectRatio((size.width.toFloat() / size.height).coerceIn(0.05f, 20f)) else Modifier
                    Page(pages, slot.page, filter, Modifier.weight(1f).then(shape), contentScale = ContentScale.FillWidth)
                }
            }
        }
        PageFit.HEIGHT -> Row(
            Modifier.fillMaxSize().horizontalScroll(rememberScrollState()),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            ordered.forEach { slot ->
                val size = pages.sizes.getOrNull(slot.page)
                val shape = if (size != null) Modifier.aspectRatio((size.width.toFloat() / size.height).coerceIn(0.05f, 20f)) else Modifier
                Page(pages, slot.page, filter, Modifier.fillMaxHeight().then(shape), contentScale = ContentScale.FillHeight)
            }
        }
        else -> Box(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).horizontalScroll(rememberScrollState())) {
            Row {
                ordered.forEach { slot ->
                    val size = pages.sizes.getOrNull(slot.page)
                    val shape = if (size != null) with(density) { Modifier.size(size.width.toDp(), size.height.toDp()) } else Modifier
                    Page(pages, slot.page, filter, shape, contentScale = ContentScale.None)
                }
            }
        }
    }
}

/** Half of a wide page, as large as the screen allows: the page laid out twice as wide, clipped. */
@Composable
private fun HalfPage(pages: ImagePages, index: Int, half: Half, size: PageSize, filter: ColorFilter?) {
    BoxWithConstraints(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
        val aspect = (size.width / 2f) / size.height
        val fitsHeight = maxWidth / maxHeight > aspect
        val width = if (fitsHeight) maxHeight * aspect else maxWidth
        val height = if (fitsHeight) maxHeight else maxWidth / aspect
        Box(Modifier.size(width, height).clipToBounds()) {
            Page(
                pages, index, filter,
                Modifier.requiredSize(width * 2, height).offset(x = if (half == Half.LEFT) width / 2 else -width / 2),
                contentScale = ContentScale.FillBounds,
            )
        }
    }
}

@Composable
private fun Strip(
    pages: ImagePages,
    page: Int,
    filter: ColorFilter?,
    end: @Composable () -> Unit,
    onShowing: (Int) -> Unit,
    onMenu: () -> Unit,
) {
    val state = rememberLazyListState(initialFirstVisibleItemIndex = page)
    LaunchedEffect(state) {
        snapshotFlow { state.firstVisibleItemIndex }.collect { if (it < pages.count) onShowing(it) }
    }
    LaunchedEffect(page) { if (page != state.firstVisibleItemIndex) state.scrollToItem(page) }
    Zoomable(onTap = { onMenu() }, onVerticalPan = { state.dispatchRawDelta(-it) }) {
        LazyColumn(state = state, modifier = Modifier.fillMaxSize()) {
            itemsIndexed(pages.pages, key = { i, _ -> i }) { i, _ ->
                val size = pages.sizes.getOrNull(i)
                // A page of unknown size takes its height from the image once it has loaded.
                val shape = if (size != null) Modifier.aspectRatio((size.width.toFloat() / size.height).coerceIn(0.05f, 20f)) else Modifier
                Page(pages, i, filter, Modifier.fillMaxWidth().then(shape), contentScale = ContentScale.FillWidth)
            }
            item(key = "end") { Box(Modifier.fillMaxWidth().height(620.dp)) { end() } }
        }
    }
}

/**
 * After the last page: the book is read (the page and 100 %), how long this sitting took and
 * its pace, the next book in the series when there is one, and starting over or closing.
 */
@Composable
private fun EndPanel(
    title: ReaderTitle,
    count: Int,
    openedAt: Long,
    seen: Int,
    next: NextBook?,
    onNext: (Int) -> Unit,
    onRestart: () -> Unit,
    onClose: () -> Unit,
) {
    val colors = KodexTheme.colors
    val ink = LocalReaderInk.current
    val seconds = ((System.currentTimeMillis() - openedAt) / 1000).coerceAtLeast(1)
    Column(
        Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(24.dp).testTag("reader-end"),
        verticalArrangement = Arrangement.spacedBy(16.dp, Alignment.CenterVertically),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Column(Modifier.widthIn(max = 480.dp).fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(14.dp),
            horizontalAlignment = Alignment.CenterHorizontally) {
            Row(
                Modifier.clip(CircleShape).background(colors.offlineSoft).padding(horizontal = 12.dp, vertical = 5.dp),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(6.dp),
            ) {
                Icon(Icons.Filled.CheckCircle, contentDescription = null, tint = colors.offline, modifier = Modifier.size(16.dp))
                Text(stringResource(R.string.reader_done, count, count), style = MaterialTheme.typography.labelMedium, color = colors.offlineText)
            }
            Text(stringResource(R.string.reader_congrats), style = MaterialTheme.typography.headlineMedium, color = ink, textAlign = TextAlign.Center)
            Text(listOfNotNull(title.series, title.title).joinToString(" · "), style = MaterialTheme.typography.bodyMedium, color = colors.textMuted,
                textAlign = TextAlign.Center)
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Stat(stringResource(R.string.reader_time), stringResource(R.string.reader_minutes, ((seconds + 59) / 60).toInt()), Modifier.weight(1f))
                Stat(stringResource(R.string.reader_pace), stringResource(R.string.reader_pace_value, (seconds / seen.coerceAtLeast(1)).toInt()), Modifier.weight(1f))
                Stat(stringResource(R.string.reading_progress), stringResource(R.string.percent, 100), Modifier.weight(1f), colors.offlineText)
            }
            if (next != null) {
                Surface(
                    shape = MaterialTheme.shapes.medium,
                    color = colors.surface1,
                    border = BorderStroke(1.dp, colors.border),
                    modifier = Modifier.fillMaxWidth().testTag("next-book"),
                ) {
                    Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(14.dp)) {
                            Cover(next.id, width = 64.dp, corner = 8.dp)
                            Column(Modifier.weight(1f)) {
                                Text(stringResource(R.string.reader_next).uppercase(), style = MaterialTheme.typography.labelSmall, color = colors.textMuted)
                                Text(next.title, style = MaterialTheme.typography.titleMedium, color = colors.text, maxLines = 2, overflow = TextOverflow.Ellipsis)
                            }
                        }
                        Button(onClick = { onNext(next.id) }, modifier = Modifier.fillMaxWidth().testTag("read-next")) {
                            Text(stringResource(R.string.reader_open_next))
                            Spacer(Modifier.width(8.dp))
                            Icon(Icons.AutoMirrored.Filled.ArrowForward, contentDescription = null, modifier = Modifier.size(18.dp))
                        }
                    }
                }
            }
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedButton(onClick = onRestart, modifier = Modifier.weight(1f).testTag("reader-restart")) {
                    Icon(Icons.Filled.Replay, contentDescription = null, modifier = Modifier.size(18.dp))
                    Spacer(Modifier.width(6.dp))
                    Text(stringResource(R.string.reader_restart), maxLines = 1, overflow = TextOverflow.Ellipsis)
                }
                OutlinedButton(onClick = onClose, modifier = Modifier.weight(1f).testTag("reader-close")) {
                    Text(stringResource(R.string.reader_close_book), maxLines = 1, overflow = TextOverflow.Ellipsis)
                }
            }
        }
    }
}

@Composable
private fun Stat(label: String, value: String, modifier: Modifier = Modifier, tint: androidx.compose.ui.graphics.Color = KodexTheme.colors.text) {
    val colors = KodexTheme.colors
    Column(
        modifier.clip(MaterialTheme.shapes.medium).background(colors.surface1).padding(horizontal = 12.dp, vertical = 10.dp),
        verticalArrangement = Arrangement.spacedBy(2.dp),
    ) {
        Text(label, style = MaterialTheme.typography.labelSmall, color = colors.textMuted, maxLines = 1)
        Text(value, style = MaterialTheme.typography.titleMedium, color = tint, maxLines = 1)
    }
}

private fun colorFilter(filter: PageFilter): ColorFilter? = when (filter) {
    PageFilter.NONE -> null
    PageFilter.GRAYSCALE -> ColorFilter.colorMatrix(ColorMatrix().apply { setToSaturation(0f) })
    PageFilter.SEPIA -> ColorFilter.colorMatrix(
        ColorMatrix(
            floatArrayOf(
                0.393f, 0.769f, 0.189f, 0f, 0f,
                0.349f, 0.686f, 0.168f, 0f, 0f,
                0.272f, 0.534f, 0.131f, 0f, 0f,
                0f, 0f, 0f, 1f, 0f,
            ),
        ),
    )
    PageFilter.INVERT -> ColorFilter.colorMatrix(
        ColorMatrix(
            floatArrayOf(
                -1f, 0f, 0f, 0f, 255f,
                0f, -1f, 0f, 0f, 255f,
                0f, 0f, -1f, 0f, 255f,
                0f, 0f, 0f, 1f, 0f,
            ),
        ),
    )
}

@Composable
private fun Page(
    pages: ImagePages,
    index: Int,
    filter: ColorFilter?,
    modifier: Modifier,
    alignment: Alignment = Alignment.Center,
    contentScale: ContentScale = ContentScale.Fit,
) {
    val context = LocalPlatformContext.current
    val window = LocalWindowInfo.current.containerSize
    // Twice the screen, so a zoomed page stays sharp; at most 4096 px on a side.
    val request = remember(pages, index) {
        ImageRequest.Builder(context)
            .data(pages.pages[index])
            .apply { pages.headers?.let { httpHeaders(it) } }
            .size((window.width * 2).coerceIn(1, 4096), (window.height * 2).coerceIn(1, 4096))
            .precision(Precision.INEXACT)
            .build()
    }
    SubcomposeAsyncImage(
        model = request,
        contentDescription = stringResource(R.string.reader_page, index + 1),
        modifier = modifier.testTag("page-$index"),
        alignment = alignment,
        contentScale = contentScale,
        colorFilter = filter,
        loading = {
            Box(Modifier.fillMaxSize().heightIn(min = 200.dp), contentAlignment = Alignment.Center) { CircularProgressIndicator() }
        },
        error = {
            Box(Modifier.fillMaxSize().heightIn(min = 200.dp).padding(24.dp), contentAlignment = Alignment.Center) {
                Text(stringResource(R.string.reader_page_failed, index + 1), color = LocalReaderInk.current, style = MaterialTheme.typography.bodyMedium)
            }
        },
        success = { SubcomposeAsyncImageContent(Modifier.testTag("page-shown-$index")) },
    )
}

/**
 * Pinch and double-tap zoom over [content], and taps with where they landed (0–1 across).
 * Unzoomed, a one-finger swipe is left alone for the pager; zoomed, it pans, until the edge
 * of the page, where the pager takes over again.
 */
@Composable
private fun Zoomable(onTap: (Float) -> Unit, onVerticalPan: ((Float) -> Unit)? = null, content: @Composable () -> Unit) {
    // A strip scrolls itself: zoomed in, an up or down swipe scrolls it instead of moving the page.
    val panVertically = onVerticalPan == null
    var scale by remember { mutableFloatStateOf(1f) }
    var offset by remember { mutableStateOf(Offset.Zero) }
    Box(
        Modifier
            .fillMaxSize()
            .pointerInput(Unit) {
                detectTapGestures(
                    onDoubleTap = { at ->
                        if (scale > 1f) {
                            scale = 1f
                            offset = Offset.Zero
                        } else {
                            scale = 2.5f
                            // Keep the tapped point where it is.
                            val center = Offset(size.width / 2f, size.height / 2f)
                            offset = clamp((center - at) * (scale - 1f), scale, size.width.toFloat(), size.height.toFloat(), panVertically)
                        }
                    },
                    onTap = { at -> onTap(at.x / size.width) },
                )
            }
            .pointerInput(Unit) {
                awaitEachGesture {
                    awaitFirstDown(requireUnconsumed = false)
                    do {
                        val event = awaitPointerEvent()
                        val fingers = event.changes.count { it.pressed }
                        if (fingers > 1 || scale > 1f) {
                            val zoom = event.calculateZoom()
                            val pan = event.calculatePan()
                            val next = (scale * zoom).coerceIn(1f, 5f)
                            val width = size.width.toFloat()
                            val maxX = width * (next - 1f) / 2f
                            val atEdge = fingers == 1 && ((pan.x > 0 && offset.x >= maxX - 0.5f) || (pan.x < 0 && offset.x <= -maxX + 0.5f))
                            if (!atEdge) {
                                scale = next
                                offset = if (next <= 1f) Offset.Zero
                                else clamp(offset + pan, next, width, size.height.toFloat(), panVertically)
                                if (!panVertically && next > 1f && pan.y != 0f) onVerticalPan(pan.y / next)
                                event.changes.forEach { if (it.positionChanged()) it.consume() }
                            }
                        }
                    } while (event.changes.any { it.pressed })
                }
            }
            .graphicsLayer {
                scaleX = scale
                scaleY = scale
                translationX = offset.x
                translationY = offset.y
            },
    ) {
        Column(Modifier.fillMaxSize()) { content() }
    }
}

private fun clamp(offset: Offset, scale: Float, width: Float, height: Float, vertically: Boolean): Offset {
    val maxX = width * (scale - 1f) / 2f
    val maxY = height * (scale - 1f) / 2f
    return Offset(offset.x.coerceIn(-maxX, maxX), if (vertically) offset.y.coerceIn(-maxY, maxY) else 0f)
}
