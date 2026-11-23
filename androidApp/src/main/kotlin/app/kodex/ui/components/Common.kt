package app.kodex.ui.components

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxScope
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.RowScope
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.automirrored.filled.MenuBook
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.KeyboardDoubleArrowLeft
import androidx.compose.material.icons.filled.Person
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.painter.Painter
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.Hyphens
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import app.kodex.R
import app.kodex.data.CardDensity
import app.kodex.data.db.DownloadState
import app.kodex.ui.LocalSession
import app.kodex.ui.theme.KodexTheme
import coil3.compose.AsyncImage
import coil3.compose.LocalPlatformContext
import coil3.network.NetworkHeaders
import coil3.network.httpHeaders
import coil3.request.ImageRequest
import java.util.Locale

/** What kind of book it is, for its badge: from its library's type, or its format in a mixed one. */
enum class MediaKind { MANGA, COMIC, BOOK }

fun mediaKind(libraryType: String?, format: String): MediaKind = when (libraryType?.lowercase()) {
    "manga" -> MediaKind.MANGA
    "comics" -> MediaKind.COMIC
    "ebooks" -> MediaKind.BOOK
    else -> if (format.lowercase() in setOf("epub", "pdf")) MediaKind.BOOK else MediaKind.COMIC
}

/** Covers drawn without the server, for the screenshots in the tests. */
val LocalCoverArt = staticCompositionLocalOf<((Int) -> Painter)?> { null }

/**
 * A book's cover from the server (kept in Coil's disk cache, so it shows offline too), 2:3 with
 * a hairline edge. [width] picks the size asked for; without it the cover fills its width.
 */
@Composable
fun Cover(bookId: Int?, modifier: Modifier = Modifier, width: Dp? = null, corner: Dp = 8.dp) {
    val session = LocalSession.current
    val context = LocalPlatformContext.current
    val colors = KodexTheme.colors
    val shape = RoundedCornerShape(corner)
    val art = LocalCoverArt.current
    Box(
        modifier.then(if (width != null) Modifier.width(width) else Modifier.fillMaxWidth())
            .aspectRatio(2f / 3f).clip(shape).background(colors.surface3),
    ) {
        if (bookId != null && art != null) {
            Image(art(bookId), contentDescription = null, contentScale = ContentScale.Crop, modifier = Modifier.fillMaxSize())
        } else if (bookId != null && session != null) {
            val small = width != null && width <= 96.dp
            val request = remember(bookId, session, small) {
                ImageRequest.Builder(context)
                    .data("${session.server}/api/books/$bookId/cover?size=${if (small) "small" else "medium"}")
                    .httpHeaders(NetworkHeaders.Builder().set("Authorization", "Bearer ${session.key}").build())
                    .build()
            }
            AsyncImage(request, contentDescription = null, contentScale = ContentScale.Crop, modifier = Modifier.fillMaxSize())
        }
        Box(Modifier.matchParentSize().border(1.dp, Color.White.copy(alpha = 0.08f), shape))
    }
}

/** The kind of book, in small capitals over the cover's corner; an arrow when it reads right to left. */
@Composable
fun MediaBadge(kind: MediaKind, format: String, rtl: Boolean, modifier: Modifier = Modifier) {
    val colors = KodexTheme.colors
    val manga = kind == MediaKind.MANGA
    val label = if (manga) stringResource(R.string.badge_manga) else format.uppercase(Locale.ROOT)
    Row(
        modifier
            .clip(RoundedCornerShape(6.dp))
            .background(Color(0xD9121316))
            .border(1.dp, Color.White.copy(alpha = if (manga) 0.22f else 0.12f), RoundedCornerShape(6.dp))
            .padding(horizontal = 6.dp, vertical = 2.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(3.dp),
    ) {
        Text(label, style = MaterialTheme.typography.labelSmall, color = Color(0xFFE3E2E6))
        if (rtl) {
            Icon(
                Icons.Filled.KeyboardDoubleArrowLeft, contentDescription = stringResource(R.string.mode_rtl),
                tint = if (colors.dark) colors.accentText else Color(0xFFE3E2E6), modifier = Modifier.size(11.dp),
            )
        }
    }
}

/** Downloaded (a teal check), on its way (a ring), or nothing. */
@Composable
fun DownloadMark(state: DownloadState?, fraction: Float?, modifier: Modifier = Modifier) {
    val colors = KodexTheme.colors
    when (state) {
        DownloadState.DONE -> Box(
            modifier.size(20.dp).clip(CircleShape).background(colors.offline),
            contentAlignment = Alignment.Center,
        ) { Icon(Icons.Filled.Check, contentDescription = stringResource(R.string.downloaded), tint = Color(0xFF04201D), modifier = Modifier.size(14.dp)) }
        DownloadState.RUNNING, DownloadState.QUEUED -> Box(
            modifier.size(20.dp).clip(CircleShape).background(Color(0xCC141416)),
            contentAlignment = Alignment.Center,
        ) {
            if (fraction != null && fraction > 0f) {
                CircularProgressIndicator(progress = { fraction ?: 0f }, modifier = Modifier.size(14.dp), strokeWidth = 2.dp, color = colors.offline)
            } else {
                CircularProgressIndicator(modifier = Modifier.size(14.dp), strokeWidth = 2.dp, color = colors.offline)
            }
        }
        else -> Unit
    }
}

/** How far a book is read, as a thin bar along the cover's foot. */
@Composable
fun ProgressStrip(fraction: Float, modifier: Modifier = Modifier, track: Color = Color(0x99000000)) {
    val colors = KodexTheme.colors
    Box(modifier.fillMaxWidth().height(4.dp).clip(CircleShape).background(track)) {
        Box(Modifier.fillMaxWidth(fraction.coerceIn(0f, 1f)).fillMaxHeight().clip(CircleShape).background(colors.accent))
    }
}

/** What a cover shows over it. */
data class CoverMarks(
    val kind: MediaKind? = null,
    val format: String = "",
    val rtl: Boolean = false,
    val progress: Float? = null,
    val finished: Boolean = false,
    val download: DownloadState? = null,
    val downloadFraction: Float? = null,
    /** A label in the cover's top corner (a volume, "Ny"). */
    val corner: String? = null,
)

/** A cover with its marks and, under it, a title and a line about it: the grids and shelves. */
@Composable
fun CoverCard(
    bookId: Int?,
    title: String,
    subtitle: String?,
    marks: CoverMarks,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    width: Dp? = null,
    overlay: (@Composable BoxScope.() -> Unit)? = null,
) {
    val colors = KodexTheme.colors
    Column(
        modifier.then(if (width != null) Modifier.width(width) else Modifier).clip(RoundedCornerShape(10.dp)).clickable(onClick = onClick),
        verticalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        Box {
            Cover(bookId, width = width)
            marks.kind?.let { MediaBadge(it, marks.format, marks.rtl, Modifier.align(Alignment.TopStart).padding(6.dp)) }
            DownloadMark(marks.download, marks.downloadFraction, Modifier.align(Alignment.TopEnd).padding(6.dp))
            if (overlay != null) {
                Box(
                    Modifier.align(Alignment.BottomCenter).fillMaxWidth()
                        .background(Brush.verticalGradient(listOf(Color.Transparent, Color(0xE6000000))))
                        .padding(start = 8.dp, end = 8.dp, top = 24.dp, bottom = 8.dp),
                    content = overlay,
                )
            } else {
                marks.corner?.let {
                    Text(
                        it,
                        style = MaterialTheme.typography.labelMedium,
                        color = Color(0xFFF3F4F6),
                        modifier = Modifier.align(Alignment.BottomStart).padding(6.dp)
                            .clip(RoundedCornerShape(6.dp)).background(Color(0xCC141416)).padding(horizontal = 6.dp, vertical = 2.dp),
                    )
                }
                val progress = marks.progress
                if (marks.finished) {
                    Box(
                        Modifier.align(Alignment.BottomEnd).padding(6.dp).size(20.dp).clip(CircleShape).background(colors.accent),
                        contentAlignment = Alignment.Center,
                    ) { Icon(Icons.Filled.Check, contentDescription = stringResource(R.string.finished), tint = colors.onAccent, modifier = Modifier.size(14.dp)) }
                } else if (progress != null && progress > 0f) {
                    ProgressStrip(progress, Modifier.align(Alignment.BottomCenter).padding(horizontal = 6.dp, vertical = 6.dp))
                }
            }
        }
        Column(Modifier.padding(horizontal = 2.dp)) {
            Text(title, style = MaterialTheme.typography.titleSmall.copy(hyphens = Hyphens.Auto), color = colors.text, maxLines = 2,
                overflow = TextOverflow.Ellipsis)
            if (!subtitle.isNullOrBlank()) {
                Text(subtitle, style = MaterialTheme.typography.bodySmall, color = colors.textMuted, maxLines = 1, overflow = TextOverflow.Ellipsis)
            }
        }
    }
}

/** The covers' columns: about three across a phone (two when they are large), more on wider screens. */
fun coverCells(density: CardDensity): GridCells = GridCells.Adaptive(if (density == CardDensity.LARGE) 150.dp else 104.dp)

/**
 * A section's title, its [count] in a small badge after it (or a dot in [mark] when that isn't
 * the accent: "new" in teal), and an action at the end ("Se alla ›").
 */
@Composable
fun SectionHeader(
    title: String,
    modifier: Modifier = Modifier,
    mark: Color = KodexTheme.colors.accent,
    action: String? = null,
    onAction: (() -> Unit)? = null,
    count: Int? = null,
    trailing: @Composable RowScope.() -> Unit = {},
) {
    val colors = KodexTheme.colors
    Row(
        modifier.fillMaxWidth().heightIn(min = 48.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        Text(title, style = MaterialTheme.typography.headlineSmall, color = colors.text, modifier = Modifier.weight(1f, fill = false),
            maxLines = 1, overflow = TextOverflow.Ellipsis)
        when {
            count != null -> Text(
                count.toString(), style = MaterialTheme.typography.labelMedium, color = colors.textMuted,
                modifier = Modifier.clip(CircleShape).background(colors.surface3).padding(horizontal = 8.dp, vertical = 1.dp),
            )
            mark != colors.accent -> Box(Modifier.size(7.dp).clip(CircleShape).background(mark))
        }
        Spacer(Modifier.weight(1f))
        trailing()
        if (action != null && onAction != null) {
            Text(
                "$action ›",
                style = MaterialTheme.typography.labelLarge,
                color = colors.accentText,
                modifier = Modifier.clip(RoundedCornerShape(8.dp)).clickable(onClick = onAction).padding(horizontal = 8.dp, vertical = 12.dp),
            )
        }
    }
}

/** A flat card: a step lighter than the background, with a hairline border. */
@Composable
fun KodexCard(modifier: Modifier = Modifier, padding: PaddingValues = PaddingValues(16.dp), content: @Composable ColumnScope.() -> Unit) {
    val colors = KodexTheme.colors
    Surface(modifier, shape = MaterialTheme.shapes.medium, color = colors.surface1, border = BorderStroke(1.dp, colors.border)) {
        Column(Modifier.padding(padding), content = content)
    }
}

/** A filter chip: dark and quiet when off, the accent when on; [count] after the label. */
@Composable
fun Pill(
    text: String,
    selected: Boolean,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    count: Int? = null,
    icon: ImageVector? = null,
) {
    val colors = KodexTheme.colors
    val shape = CircleShape
    Row(
        modifier
            .heightIn(min = 40.dp)
            .clip(shape)
            .background(if (selected) colors.accentSoft else colors.surface1)
            .border(1.dp, if (selected) colors.accent else colors.border, shape)
            .clickable(onClick = onClick)
            .padding(horizontal = 14.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        val ink = if (selected) colors.accentText else colors.textMuted
        icon?.let { Icon(it, contentDescription = null, tint = ink, modifier = Modifier.size(18.dp)) }
        Text(text, style = MaterialTheme.typography.labelLarge, color = if (selected) colors.accentText else colors.text)
        if (count != null) {
            Text(
                count.toString(),
                style = MaterialTheme.typography.labelMedium,
                color = ink,
                modifier = Modifier.clip(CircleShape).background(if (selected) colors.accent.copy(alpha = 0.18f) else colors.surface3)
                    .padding(horizontal = 7.dp, vertical = 1.dp),
            )
        }
    }
}

/** Kodex's mark: an open book in the accent, on a soft accent square. */
@Composable
fun Logo(modifier: Modifier = Modifier, size: Dp = 40.dp) {
    val colors = KodexTheme.colors
    Box(
        modifier.size(size).clip(RoundedCornerShape(size * 0.3f)).background(colors.accentSoft),
        contentAlignment = Alignment.Center,
    ) {
        Icon(Icons.AutoMirrored.Filled.MenuBook, contentDescription = null, tint = colors.accentText, modifier = Modifier.size(size * 0.55f))
    }
}

/** A small capital line over a title or a section ("KODEX", "AKTIV LÄSNING"). */
@Composable
fun Overline(text: String, modifier: Modifier = Modifier, color: Color = KodexTheme.colors.textMuted) {
    Text(text.uppercase(), style = MaterialTheme.typography.labelSmall, color = color, maxLines = 1, overflow = TextOverflow.Ellipsis,
        modifier = modifier)
}

/** The round account button at the end of a tab's bar: it opens the settings. */
@Composable
fun AccountButton(onClick: () -> Unit, modifier: Modifier = Modifier) {
    val colors = KodexTheme.colors
    IconButton(onClick = onClick, modifier = modifier.testTag("account")) {
        Box(Modifier.size(34.dp).clip(CircleShape).background(colors.accentSoft), contentAlignment = Alignment.Center) {
            Icon(Icons.Filled.Person, contentDescription = stringResource(R.string.account), tint = colors.accentText, modifier = Modifier.size(20.dp))
        }
    }
}

/**
 * The top of a tab: the mark, "KODEX" small over what the tab is, the tab's actions, and (with
 * [onAccount]) the account button at the end.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun BrandBar(subtitle: String, onAccount: (() -> Unit)? = null, actions: @Composable RowScope.() -> Unit = {}) {
    val colors = KodexTheme.colors
    TopAppBar(
        title = {
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                Logo()
                Column {
                    Overline(stringResource(R.string.app_name), color = colors.accentText)
                    Text(subtitle, style = MaterialTheme.typography.titleLarge, color = colors.text, maxLines = 1, overflow = TextOverflow.Ellipsis)
                }
            }
        },
        actions = {
            actions()
            if (onAccount != null) AccountButton(onAccount)
        },
        colors = TopAppBarDefaults.topAppBarColors(containerColor = colors.background, scrolledContainerColor = colors.surface1),
    )
}

/** A tab's big title under its bar, a line about it, and something at the end (a status chip). */
@Composable
fun PageHeading(title: String, modifier: Modifier = Modifier, line: String? = null, trailing: @Composable RowScope.() -> Unit = {}) {
    val colors = KodexTheme.colors
    Row(modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(2.dp)) {
            Text(title, style = MaterialTheme.typography.headlineLarge, color = colors.text, maxLines = 2, overflow = TextOverflow.Ellipsis)
            if (!line.isNullOrBlank()) {
                Text(line, style = MaterialTheme.typography.bodyMedium, color = colors.textMuted, maxLines = 2, overflow = TextOverflow.Ellipsis)
            }
        }
        trailing()
    }
}

/** A small rounded chip with a dot: the server's state ("● Synkad 2 min sedan"), "Redo offline". */
@Composable
fun StatusChip(text: String, modifier: Modifier = Modifier, dot: Color = KodexTheme.colors.offline, icon: ImageVector? = null) {
    val colors = KodexTheme.colors
    Row(
        modifier.clip(CircleShape).background(colors.surface1).border(1.dp, colors.borderSubtle, CircleShape)
            .padding(horizontal = 12.dp, vertical = 6.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        if (icon != null) {
            Icon(icon, contentDescription = null, tint = dot, modifier = Modifier.size(16.dp))
        } else {
            Box(Modifier.size(7.dp).clip(CircleShape).background(dot))
        }
        Text(text, style = MaterialTheme.typography.labelMedium, color = colors.textMuted, maxLines = 1, overflow = TextOverflow.Ellipsis)
    }
}

/** A page under a tab: back, its title, and its actions. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun Bar(title: String, onBack: (() -> Unit)? = null, actions: @Composable RowScope.() -> Unit = {}) {
    val colors = KodexTheme.colors
    TopAppBar(
        title = { Text(title, maxLines = 1, overflow = TextOverflow.Ellipsis, style = MaterialTheme.typography.titleLarge) },
        navigationIcon = {
            if (onBack != null) {
                IconButton(onClick = onBack) { Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = stringResource(R.string.back)) }
            }
        },
        actions = actions,
        colors = TopAppBarDefaults.topAppBarColors(containerColor = colors.background, scrolledContainerColor = colors.surface1),
    )
}

/** A screen's content no wider than reads well, centred on a wide screen. */
fun Modifier.readable(max: Dp = 760.dp): Modifier = this.widthIn(max = max).fillMaxWidth()

@Composable
fun Empty(text: String, modifier: Modifier = Modifier) {
    Box(modifier.fillMaxSize().padding(32.dp), contentAlignment = Alignment.Center) {
        Text(text, textAlign = TextAlign.Center, style = MaterialTheme.typography.bodyLarge, color = KodexTheme.colors.textMuted)
    }
}

@Composable
fun details(format: String, pages: Int?, bytes: Long): String =
    listOfNotNull(format.uppercase(Locale.ROOT), pages?.let { stringResource(R.string.pages_count, it) }, size(bytes)).joinToString(" · ")

/** A book's number as the series counts: #12, Kap. 12 in manga, Vol. 3 for a collected edition. */
@Composable
fun numberLabel(number: Double?, editionType: String, libraryType: String?): String? {
    number ?: return null
    val text = if (number % 1.0 == 0.0) number.toLong().toString() else number.toString()
    return when {
        editionType == "collected" -> stringResource(R.string.number_volume, text)
        libraryType?.lowercase() == "manga" -> stringResource(R.string.number_chapter, text)
        else -> stringResource(R.string.number_issue, text)
    }
}

fun size(bytes: Long): String = when {
    bytes >= 1_000_000_000 -> String.format(Locale.getDefault(), "%.1f GB", bytes / 1e9)
    bytes >= 1_000_000 -> String.format(Locale.getDefault(), "%.0f MB", bytes / 1e6)
    else -> String.format(Locale.getDefault(), "%.0f kB", bytes / 1e3)
}

fun Modifier.clickableRow(onClick: () -> Unit): Modifier = clickable(onClick = onClick)
