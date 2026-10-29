package app.kodex.reader

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawing
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.layout.windowInsetsPadding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.automirrored.filled.List
import androidx.compose.material.icons.filled.Bookmark
import androidx.compose.material.icons.filled.BookmarkBorder
import androidx.compose.material.icons.filled.BrightnessMedium
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.KeyboardDoubleArrowLeft
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Slider
import androidx.compose.material3.SliderDefaults
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import app.kodex.R
import app.kodex.data.ImageMode
import app.kodex.data.PageFit
import app.kodex.data.db.BookmarkEntity
import app.kodex.ui.library.bookmarkLabel
import app.kodex.ui.theme.KodexTheme

/** What the reader's bars say about the book: its title, its series, and whether it reads right to left. */
data class ReaderTitle(val title: String, val series: String? = null, val rtl: Boolean = false)

/** The bookmarks: whether the place on screen has one, the list, and what to do with them. */
class BookmarkControls(
    val marked: Boolean,
    val list: List<BookmarkEntity>,
    val toggle: () -> Unit,
    val open: (BookmarkEntity) -> Unit,
    val remove: (BookmarkEntity) -> Unit,
)

/** The screen's light while reading: a brightness (below 0 the device's own) and black around the pages. */
class LightControls(
    val brightness: Float,
    val pureBlack: Boolean,
    /** While the slider moves (the window only). */
    val onBrightness: (Float) -> Unit,
    /** Where it was let go, or -1 for the device's own: kept for the next book. */
    val onBrightnessDone: (Float) -> Unit,
    val onPureBlack: (Boolean) -> Unit,
)

/**
 * The reader's bars: back, the title and the bookmarks on top; below, in a floating panel,
 * where in the book (a slider), how pages turn and fit, and the light.
 */
@OptIn(ExperimentalLayoutApi::class)
@Composable
fun ReaderChrome(
    title: ReaderTitle,
    page: Int,
    count: Int,
    mode: ImageMode?,
    onMode: (ImageMode) -> Unit,
    fit: PageFit?,
    onFit: (PageFit) -> Unit,
    bookmarks: BookmarkControls?,
    light: LightControls,
    onSeek: (Int) -> Unit,
    onClose: () -> Unit,
    extra: @Composable () -> Unit = {},
) {
    val colors = KodexTheme.colors
    var showMarks by remember { mutableStateOf(false) }
    Box(Modifier.fillMaxSize().testTag("reader-chrome")) {
        TopBar(title, onClose, Modifier.align(Alignment.TopCenter), bookmarks, onList = { showMarks = !showMarks })
        Column(
            Modifier.align(Alignment.BottomCenter).fillMaxWidth().windowInsetsPadding(WindowInsets.safeDrawing)
                .padding(horizontal = 12.dp, vertical = 8.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            if (showMarks && bookmarks != null) BookmarkPanel(bookmarks) { showMarks = false }
            Surface(
                shape = RoundedCornerShape(24.dp),
                color = colors.surface2.copy(alpha = 0.96f),
                border = BorderStroke(1.dp, colors.border),
                modifier = Modifier.widthIn(max = 720.dp).fillMaxWidth(),
            ) {
                Column(Modifier.padding(horizontal = 16.dp, vertical = 12.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                    if (count > 1) {
                        var dragging by remember(page) { mutableFloatStateOf(page.toFloat()) }
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Text((dragging.toInt() + 1).toString(), style = MaterialTheme.typography.labelLarge, color = colors.accentText,
                                modifier = Modifier.width(36.dp))
                            Slider(
                                value = dragging,
                                onValueChange = { dragging = it },
                                onValueChangeFinished = { onSeek(dragging.toInt()) },
                                valueRange = 0f..(count - 1).toFloat(),
                                modifier = Modifier.weight(1f).testTag("reader-slider"),
                                colors = SliderDefaults.colors(inactiveTrackColor = colors.surface3),
                            )
                            Text(count.toString(), style = MaterialTheme.typography.labelLarge, color = colors.textMuted,
                                modifier = Modifier.width(36.dp).padding(start = 8.dp))
                        }
                    }
                    if (mode != null || fit != null) {
                        FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                            if (mode != null) {
                                Segment(
                                    listOf(
                                        ImageMode.PAGED_LTR to stringResource(R.string.mode_ltr_short),
                                        ImageMode.PAGED_RTL to stringResource(R.string.mode_rtl_short),
                                        ImageMode.VERTICAL to stringResource(R.string.mode_vertical_short),
                                    ),
                                    mode, onMode, Modifier.testTag("reader-mode"),
                                )
                            }
                            if (fit != null && mode != ImageMode.VERTICAL) {
                                Segment(
                                    listOf(
                                        PageFit.PAGE to stringResource(R.string.fit_page),
                                        PageFit.WIDTH to stringResource(R.string.fit_width),
                                        PageFit.HEIGHT to stringResource(R.string.fit_height),
                                        PageFit.ORIGINAL to stringResource(R.string.fit_original),
                                    ),
                                    fit, onFit, Modifier.testTag("reader-fit"),
                                )
                            }
                        }
                    }
                    Light(light, extra)
                }
            }
            if (count > 1) {
                Text(
                    stringResource(R.string.reader_position, page + 1, count, (page + 1) * 100 / count),
                    style = MaterialTheme.typography.labelMedium,
                    color = colors.textMuted,
                    modifier = Modifier.clip(CircleShape).background(colors.background.copy(alpha = 0.7f)).padding(horizontal = 10.dp, vertical = 2.dp),
                )
            }
        }
    }
}

@Composable
private fun Light(light: LightControls, extra: @Composable () -> Unit) {
    val colors = KodexTheme.colors
    var level by remember(light.brightness) { mutableFloatStateOf(if (light.brightness < 0) 0.5f else light.brightness) }
    val auto = light.brightness < 0
    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        Icon(Icons.Filled.BrightnessMedium, contentDescription = stringResource(R.string.reader_brightness), tint = colors.textMuted,
            modifier = Modifier.size(20.dp))
        Slider(
            value = level,
            onValueChange = {
                level = it
                light.onBrightness(it)
            },
            onValueChangeFinished = { light.onBrightnessDone(level) },
            valueRange = 0.02f..1f,
            modifier = Modifier.weight(1f).testTag("reader-brightness"),
            colors = SliderDefaults.colors(
                thumbColor = if (auto) colors.textMuted else colors.text,
                activeTrackColor = if (auto) colors.textFaint else colors.text,
                inactiveTrackColor = colors.surface3,
            ),
        )
        Small(if (auto) stringResource(R.string.reader_brightness_auto) else stringResource(R.string.percent, (level * 100).toInt()), auto) {
            light.onBrightnessDone(if (auto) level else -1f)
        }
        Small(stringResource(R.string.reader_pure_black), light.pureBlack, Modifier.testTag("reader-black")) { light.onPureBlack(!light.pureBlack) }
        extra()
    }
}

/** A small pill in the reader's panel, with a dot when on. */
@Composable
private fun Small(label: String, on: Boolean, modifier: Modifier = Modifier, onClick: () -> Unit) {
    val colors = KodexTheme.colors
    Row(
        modifier.heightIn(min = 40.dp).clip(RoundedCornerShape(12.dp))
            .background(if (on) colors.accentSoft else colors.surface1)
            .border(1.dp, if (on) colors.accent else colors.border, RoundedCornerShape(12.dp))
            .clickable(onClick = onClick).padding(horizontal = 10.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        if (on) Box(Modifier.size(6.dp).clip(CircleShape).background(colors.accent))
        Text(label, style = MaterialTheme.typography.labelLarge, color = if (on) colors.accentText else colors.text)
    }
}

/** A row of choices joined together; the chosen one in the accent. */
@Composable
fun <T> Segment(options: List<Pair<T, String>>, selected: T, onSelect: (T) -> Unit, modifier: Modifier = Modifier) {
    val colors = KodexTheme.colors
    Row(modifier.clip(RoundedCornerShape(14.dp)).background(colors.surface1).border(1.dp, colors.border, RoundedCornerShape(14.dp)).padding(3.dp)) {
        options.forEach { (value, label) ->
            val on = value == selected
            Box(
                Modifier.heightIn(min = 40.dp).clip(RoundedCornerShape(11.dp))
                    .background(if (on) colors.accentSoft else colors.surface1)
                    .then(if (on) Modifier.border(1.dp, colors.accent, RoundedCornerShape(11.dp)) else Modifier)
                    .clickable { onSelect(value) }.padding(horizontal = 12.dp),
                contentAlignment = Alignment.Center,
            ) {
                Text(label, style = MaterialTheme.typography.labelLarge, color = if (on) colors.accentText else colors.textMuted)
            }
        }
    }
}

@Composable
private fun BookmarkPanel(bookmarks: BookmarkControls, onClose: () -> Unit) {
    val colors = KodexTheme.colors
    Surface(
        shape = RoundedCornerShape(20.dp),
        color = colors.surface2.copy(alpha = 0.97f),
        border = BorderStroke(1.dp, colors.border),
        modifier = Modifier.widthIn(max = 720.dp).fillMaxWidth().heightIn(max = 280.dp).testTag("reader-bookmarks"),
    ) {
        Column(Modifier.verticalScroll(rememberScrollState()).padding(vertical = 6.dp)) {
            Text(stringResource(R.string.bookmarks), style = MaterialTheme.typography.titleSmall, color = colors.text,
                modifier = Modifier.padding(horizontal = 16.dp, vertical = 8.dp))
            if (bookmarks.list.isEmpty()) {
                Text(stringResource(R.string.bookmarks_none), style = MaterialTheme.typography.bodySmall, color = colors.textMuted,
                    modifier = Modifier.padding(horizontal = 16.dp, vertical = 8.dp))
            }
            bookmarks.list.forEach { mark ->
                Row(
                    Modifier.fillMaxWidth().clickable {
                        bookmarks.open(mark)
                        onClose()
                    }.padding(start = 16.dp, end = 4.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Icon(Icons.Filled.Bookmark, contentDescription = null, tint = colors.accentText, modifier = Modifier.size(18.dp))
                    Spacer(Modifier.width(12.dp))
                    Text(bookmarkLabel(mark), style = MaterialTheme.typography.bodyMedium, color = colors.text, modifier = Modifier.weight(1f),
                        maxLines = 1, overflow = TextOverflow.Ellipsis)
                    IconButton(onClick = { bookmarks.remove(mark) }) {
                        Icon(Icons.Filled.Delete, contentDescription = stringResource(R.string.remove_bookmark), tint = colors.textMuted)
                    }
                }
            }
        }
    }
}

@Composable
fun TopBar(
    title: ReaderTitle,
    onClose: () -> Unit,
    modifier: Modifier = Modifier,
    bookmarks: BookmarkControls? = null,
    onList: () -> Unit = {},
) {
    val colors = KodexTheme.colors
    Row(
        modifier.fillMaxWidth().background(colors.background.copy(alpha = 0.94f)).windowInsetsPadding(WindowInsets.safeDrawing).padding(4.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        IconButton(onClick = onClose) {
            Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = stringResource(R.string.back), tint = colors.text)
        }
        Column(Modifier.weight(1f).padding(horizontal = 4.dp), horizontalAlignment = Alignment.CenterHorizontally) {
            if (title.series != null || title.rtl) {
                Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    title.series?.let {
                        Text(it.uppercase(), style = MaterialTheme.typography.labelMedium, color = colors.textMuted, maxLines = 1,
                            overflow = TextOverflow.Ellipsis, modifier = Modifier.weight(1f, fill = false))
                    }
                    if (title.rtl) {
                        Row(
                            Modifier.clip(RoundedCornerShape(6.dp)).background(colors.accentSoft).border(1.dp, colors.accent, RoundedCornerShape(6.dp))
                                .padding(horizontal = 5.dp, vertical = 1.dp),
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            Icon(Icons.Filled.KeyboardDoubleArrowLeft, contentDescription = stringResource(R.string.mode_rtl), tint = colors.accentText,
                                modifier = Modifier.size(12.dp))
                        }
                    }
                }
            }
            Text(title.title, color = colors.text, maxLines = 1, overflow = TextOverflow.Ellipsis, style = MaterialTheme.typography.titleMedium)
        }
        if (bookmarks != null) {
            IconButton(onClick = bookmarks.toggle, modifier = Modifier.testTag("reader-bookmark")) {
                Icon(
                    if (bookmarks.marked) Icons.Filled.Bookmark else Icons.Filled.BookmarkBorder,
                    contentDescription = stringResource(if (bookmarks.marked) R.string.remove_bookmark else R.string.add_bookmark),
                    tint = if (bookmarks.marked) colors.accent else colors.text,
                )
            }
            IconButton(onClick = onList, modifier = Modifier.testTag("reader-bookmark-list")) {
                Icon(Icons.AutoMirrored.Filled.List, contentDescription = stringResource(R.string.bookmarks), tint = colors.text)
            }
        }
    }
}
