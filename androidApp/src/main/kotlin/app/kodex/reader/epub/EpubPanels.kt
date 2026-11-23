package app.kodex.reader.epub

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
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.TextFields
import androidx.compose.material.icons.automirrored.filled.List
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Slider
import androidx.compose.material3.SliderDefaults
import androidx.compose.material3.Surface
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import app.kodex.R
import app.kodex.data.AppSettings
import app.kodex.data.EpubColumns
import app.kodex.data.EpubFont
import app.kodex.data.EpubMargins
import app.kodex.data.EpubSpacing
import app.kodex.data.EpubTheme
import app.kodex.reader.Segment
import app.kodex.ui.components.Overline
import app.kodex.ui.theme.KodexTheme
import org.readium.r2.navigator.epub.EpubPreferences
import org.readium.r2.navigator.preferences.ColumnCount
import org.readium.r2.navigator.preferences.TextAlign
import org.readium.r2.navigator.preferences.Theme
import org.readium.r2.shared.ExperimentalReadiumApi
import org.readium.r2.shared.publication.Link
import org.readium.r2.navigator.preferences.Color as ReadiumColor
import org.readium.r2.navigator.preferences.FontFamily as ReadiumFont

/**
 * The app's e-book settings as Readium's preferences. Left at their defaults, the book's own
 * styles are kept; a font, a spacing or justified text asks Readium to set the publisher's aside.
 */
@OptIn(ExperimentalReadiumApi::class)
fun epubPreferences(s: AppSettings, appDark: Boolean): EpubPreferences {
    val theme = when (s.epubTheme) {
        EpubTheme.AUTO -> if (appDark || s.pureBlack) Theme.DARK else Theme.LIGHT
        EpubTheme.LIGHT -> Theme.LIGHT
        EpubTheme.SEPIA -> Theme.SEPIA
        EpubTheme.DARK, EpubTheme.BLACK -> Theme.DARK
    }
    val black = s.epubTheme == EpubTheme.BLACK || (s.epubTheme == EpubTheme.AUTO && s.pureBlack)
    val own = s.epubFont == EpubFont.PUBLISHER && s.epubSpacing == EpubSpacing.NORMAL && !s.epubJustify
    return EpubPreferences(
        theme = theme,
        backgroundColor = if (black) ReadiumColor(android.graphics.Color.BLACK) else null,
        fontFamily = when (s.epubFont) {
            EpubFont.PUBLISHER -> null
            EpubFont.SERIF -> ReadiumFont.SERIF
            EpubFont.SANS -> ReadiumFont.SANS_SERIF
        },
        fontSize = s.epubSize.toDouble(),
        lineHeight = when (s.epubSpacing) {
            EpubSpacing.TIGHT -> 1.25
            EpubSpacing.NORMAL -> null
            EpubSpacing.LOOSE -> 1.8
        },
        pageMargins = when (s.epubMargins) {
            EpubMargins.NARROW -> 0.5
            EpubMargins.NORMAL -> 1.0
            EpubMargins.WIDE -> 1.75
        },
        publisherStyles = own,
        scroll = s.epubScroll,
        textAlign = if (s.epubJustify) TextAlign.JUSTIFY else null,
        columnCount = when (s.epubColumns) {
            EpubColumns.AUTO -> ColumnCount.AUTO
            EpubColumns.ONE -> ColumnCount.ONE
            EpubColumns.TWO -> ColumnCount.TWO
        },
    )
}

/** A panel floating over the book, as the reader's bar does: a title, a close button and its content. */
@Composable
private fun Panel(title: String, tag: String, onClose: () -> Unit, content: @Composable () -> Unit) {
    val colors = KodexTheme.colors
    Surface(
        shape = RoundedCornerShape(24.dp),
        color = colors.surface2.copy(alpha = 0.98f),
        border = BorderStroke(1.dp, colors.border),
        modifier = Modifier.widthIn(max = 720.dp).fillMaxWidth().heightIn(max = 520.dp).testTag(tag),
    ) {
        Column(Modifier.verticalScroll(rememberScrollState()).padding(horizontal = 16.dp, vertical = 8.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(title, style = MaterialTheme.typography.titleMedium, color = colors.text, modifier = Modifier.weight(1f))
                IconButton(onClick = onClose) { Icon(Icons.Filled.Close, contentDescription = stringResource(R.string.close), tint = colors.textMuted) }
            }
            content()
        }
    }
}

@Composable
private fun Label(text: String) = Overline(text, Modifier.padding(top = 14.dp, bottom = 8.dp))

/** "Text och utseende": the page's colours, the font, its size, the spacing, the margins, and how pages go. */
@OptIn(ExperimentalLayoutApi::class)
@Composable
fun EpubTextPanel(settings: AppSettings, update: ((AppSettings) -> AppSettings) -> Unit, onClose: () -> Unit) {
    val colors = KodexTheme.colors
    Panel(stringResource(R.string.epub_text), "epub-text", onClose) {
        Label(stringResource(R.string.epub_theme))
        FlowRow(horizontalArrangement = Arrangement.spacedBy(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            listOf(
                Triple(EpubTheme.AUTO, R.string.epub_theme_auto, colors.background),
                Triple(EpubTheme.LIGHT, R.string.epub_theme_light, Color(0xFFFFFFFF)),
                Triple(EpubTheme.SEPIA, R.string.epub_theme_sepia, Color(0xFFFAF4E8)),
                Triple(EpubTheme.DARK, R.string.epub_theme_dark, Color(0xFF121316)),
                Triple(EpubTheme.BLACK, R.string.epub_theme_black, Color(0xFF000000)),
            ).forEach { (theme, label, fill) ->
                val on = settings.epubTheme == theme
                Column(
                    Modifier.clip(RoundedCornerShape(12.dp)).clickable { update { it.copy(epubTheme = theme) } }.padding(4.dp)
                        .testTag("epub-theme-${theme.name.lowercase()}"),
                    horizontalAlignment = Alignment.CenterHorizontally,
                    verticalArrangement = Arrangement.spacedBy(4.dp),
                ) {
                    Box(
                        Modifier.size(44.dp).clip(CircleShape).background(fill)
                            .border(2.dp, if (on) colors.accent else colors.border, CircleShape),
                        contentAlignment = Alignment.Center,
                    ) {
                        if (on) Icon(Icons.Filled.Check, contentDescription = null, tint = colors.accent, modifier = Modifier.size(20.dp))
                    }
                    Text(stringResource(label), style = MaterialTheme.typography.labelMedium, color = if (on) colors.accentText else colors.textMuted)
                }
            }
        }

        Label(stringResource(R.string.epub_font))
        Segment(
            listOf(
                EpubFont.PUBLISHER to stringResource(R.string.epub_font_publisher),
                EpubFont.SERIF to stringResource(R.string.epub_font_serif),
                EpubFont.SANS to stringResource(R.string.epub_font_sans),
            ),
            settings.epubFont, { font -> update { it.copy(epubFont = font) } }, Modifier.testTag("epub-font"),
        )

        Label(stringResource(R.string.epub_size))
        var size by remember(settings.epubSize) { mutableFloatStateOf(settings.epubSize) }
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            Text("A", style = MaterialTheme.typography.labelLarge, color = colors.textMuted, fontFamily = FontFamily.Serif)
            Slider(
                value = size,
                onValueChange = { size = it },
                onValueChangeFinished = { update { s -> s.copy(epubSize = size) } },
                valueRange = 0.7f..2.2f,
                modifier = Modifier.weight(1f).testTag("epub-size"),
                colors = SliderDefaults.colors(inactiveTrackColor = colors.surface3),
            )
            Text("A", style = MaterialTheme.typography.headlineSmall, color = colors.text, fontFamily = FontFamily.Serif)
            Text(stringResource(R.string.percent, (size * 100).toInt()), style = MaterialTheme.typography.labelMedium, color = colors.textMuted,
                modifier = Modifier.widthIn(min = 44.dp))
        }

        Label(stringResource(R.string.epub_spacing))
        Segment(
            listOf(
                EpubSpacing.TIGHT to stringResource(R.string.epub_spacing_tight),
                EpubSpacing.NORMAL to stringResource(R.string.epub_spacing_normal),
                EpubSpacing.LOOSE to stringResource(R.string.epub_spacing_loose),
            ),
            settings.epubSpacing, { spacing -> update { it.copy(epubSpacing = spacing) } },
        )

        Label(stringResource(R.string.epub_margins))
        Segment(
            listOf(
                EpubMargins.NARROW to stringResource(R.string.epub_margins_narrow),
                EpubMargins.NORMAL to stringResource(R.string.epub_margins_normal),
                EpubMargins.WIDE to stringResource(R.string.epub_margins_wide),
            ),
            settings.epubMargins, { margins -> update { it.copy(epubMargins = margins) } },
        )

        Label(stringResource(R.string.epub_layout))
        FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Segment(
                listOf(false to stringResource(R.string.epub_paged), true to stringResource(R.string.epub_scroll)),
                settings.epubScroll, { scroll -> update { it.copy(epubScroll = scroll) } }, Modifier.testTag("epub-scroll"),
            )
            if (!settings.epubScroll) {
                Segment(
                    listOf(
                        EpubColumns.AUTO to stringResource(R.string.epub_columns_auto),
                        EpubColumns.ONE to stringResource(R.string.epub_columns_one),
                        EpubColumns.TWO to stringResource(R.string.epub_columns_two),
                    ),
                    settings.epubColumns, { columns -> update { it.copy(epubColumns = columns) } }, Modifier.testTag("epub-columns"),
                )
            }
        }

        Row(Modifier.fillMaxWidth().padding(vertical = 10.dp), verticalAlignment = Alignment.CenterVertically) {
            Text(stringResource(R.string.epub_justify), style = MaterialTheme.typography.bodyLarge, color = colors.text, modifier = Modifier.weight(1f))
            Switch(checked = settings.epubJustify, onCheckedChange = { on -> update { it.copy(epubJustify = on) } },
                modifier = Modifier.testTag("epub-justify"))
        }
    }
}

/** A book's table of contents, flattened with each heading's depth. */
fun contents(links: List<Link>, depth: Int = 0): List<Pair<Int, Link>> =
    links.flatMap { link -> listOf(depth to link) + contents(link.children, depth + 1) }

/** "Innehåll": the chapters, the one being read marked; a tap goes there. */
@Composable
fun EpubContentsPanel(entries: List<Pair<Int, Link>>, current: String?, onOpen: (Link) -> Unit, onClose: () -> Unit) {
    val colors = KodexTheme.colors
    Panel(stringResource(R.string.epub_contents), "epub-contents", onClose) {
        if (entries.isEmpty()) {
            Text(stringResource(R.string.epub_contents_none), style = MaterialTheme.typography.bodyMedium, color = colors.textMuted,
                modifier = Modifier.padding(vertical = 8.dp))
        }
        entries.forEach { (depth, link) ->
            val title = link.title?.takeIf { it.isNotBlank() } ?: link.href.toString()
            val here = current != null && title == current
            Row(
                Modifier.fillMaxWidth().heightIn(min = 44.dp).clip(RoundedCornerShape(10.dp))
                    .background(if (here) colors.accentSoft else Color.Transparent)
                    .clickable { onOpen(link) }.padding(start = (12 + depth * 16).dp, end = 12.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(title, style = if (depth == 0) MaterialTheme.typography.titleSmall else MaterialTheme.typography.bodyMedium,
                    color = if (here) colors.accentText else colors.text, maxLines = 2, overflow = TextOverflow.Ellipsis)
            }
        }
    }
}

/** The reader bar's buttons for an e-book: the contents and the text's look. */
@Composable
fun EpubButtons(onContents: () -> Unit, onText: () -> Unit) {
    val colors = KodexTheme.colors
    IconButton(onClick = onContents, modifier = Modifier.testTag("epub-contents-open")) {
        Icon(Icons.AutoMirrored.Filled.List, contentDescription = stringResource(R.string.epub_contents), tint = colors.text)
    }
    IconButton(onClick = onText, modifier = Modifier.testTag("epub-text-open")) {
        Icon(Icons.Filled.TextFields, contentDescription = stringResource(R.string.epub_text), tint = colors.text)
    }
}
