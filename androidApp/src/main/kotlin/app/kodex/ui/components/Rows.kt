package app.kodex.ui.components

import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.Download
import androidx.compose.material.icons.filled.Pause
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material3.Checkbox
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import app.kodex.R
import app.kodex.data.db.BookRow
import app.kodex.data.db.DownloadState
import app.kodex.ui.theme.KodexTheme

/** Whether a book is read, being read, or not yet: a mark at the start of its row. */
@Composable
fun ReadMark(finished: Boolean, reading: Boolean, modifier: Modifier = Modifier) {
    val colors = KodexTheme.colors
    Box(
        modifier.size(30.dp).clip(CircleShape).background(
            when {
                finished -> colors.accentSoft
                reading -> colors.accent
                else -> colors.surface1
            },
        ),
        contentAlignment = Alignment.Center,
    ) {
        when {
            finished -> Icon(Icons.Filled.Check, contentDescription = stringResource(R.string.finished), tint = colors.accentText,
                modifier = Modifier.size(16.dp))
            reading -> Icon(Icons.Filled.PlayArrow, contentDescription = stringResource(R.string.reading), tint = colors.onAccent,
                modifier = Modifier.size(18.dp))
            else -> Box(Modifier.size(7.dp).clip(CircleShape).background(colors.textFaint))
        }
    }
}

/**
 * A book's download, as a button: an outlined circle to download it, a ring while it comes (a
 * tap pauses it), a paused or failed one to go on, and a teal check once it is on the device.
 */
@Composable
fun DownloadButton(
    state: DownloadState?,
    fraction: Float?,
    onDownload: () -> Unit,
    onPause: () -> Unit,
    onResume: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val colors = KodexTheme.colors
    when (state) {
        DownloadState.DONE -> Box(Modifier.size(48.dp), contentAlignment = Alignment.Center) {
            Box(modifier.size(26.dp).clip(CircleShape).background(colors.offline), contentAlignment = Alignment.Center) {
                Icon(Icons.Filled.Check, contentDescription = stringResource(R.string.downloaded), tint = colors.onAccent,
                    modifier = Modifier.size(16.dp))
            }
        }
        DownloadState.RUNNING, DownloadState.QUEUED -> IconButton(onClick = onPause, modifier = modifier.testTag("pause-download")) {
            Box(contentAlignment = Alignment.Center) {
                if (state == DownloadState.RUNNING && fraction != null && fraction > 0f) {
                    CircularProgressIndicator(progress = { fraction ?: 0f }, modifier = Modifier.size(26.dp), strokeWidth = 2.5.dp,
                        color = colors.offline, trackColor = colors.surface3)
                } else {
                    CircularProgressIndicator(modifier = Modifier.size(26.dp), strokeWidth = 2.5.dp, color = colors.offline,
                        trackColor = colors.surface3)
                }
                Icon(Icons.Filled.Pause, contentDescription = stringResource(R.string.pause), tint = colors.textMuted, modifier = Modifier.size(12.dp))
            }
        }
        DownloadState.PAUSED, DownloadState.FAILED -> IconButton(onClick = onResume, modifier = modifier.testTag("resume-download")) {
            Box(
                Modifier.size(26.dp).clip(CircleShape)
                    .border(1.5.dp, if (state == DownloadState.FAILED) colors.danger else colors.border, CircleShape),
                contentAlignment = Alignment.Center,
            ) {
                Icon(
                    if (state == DownloadState.FAILED) Icons.Filled.Refresh else Icons.Filled.PlayArrow,
                    contentDescription = stringResource(if (state == DownloadState.FAILED) R.string.retry else R.string.resume),
                    tint = if (state == DownloadState.FAILED) colors.danger else colors.textMuted,
                    modifier = Modifier.size(15.dp),
                )
            }
        }
        null -> IconButton(onClick = onDownload, modifier = modifier.testTag("row-download")) {
            Box(Modifier.size(26.dp).clip(CircleShape).border(1.5.dp, colors.border, CircleShape), contentAlignment = Alignment.Center) {
                Icon(Icons.Filled.Download, contentDescription = stringResource(R.string.download), tint = colors.textMuted,
                    modifier = Modifier.size(15.dp))
            }
        }
    }
}

/** What a row says about a book: its pages and size, then read, where it is, or how its download goes. */
@Composable
fun bookState(book: BookRow): String {
    val parts = mutableListOf<String>()
    book.pageCount?.let { parts += stringResource(R.string.pages_count, it) }
    parts += size(book.fileSize)
    val total = book.downloadTotal ?: 0L
    parts += when {
        book.downloadState == DownloadState.RUNNING && total > 0 ->
            stringResource(R.string.downloading_percent, ((book.downloadBytes ?: 0L) * 100 / total).toInt())
        book.downloadState == DownloadState.QUEUED -> stringResource(R.string.download_queued)
        book.downloadState == DownloadState.PAUSED -> stringResource(R.string.download_paused)
        book.downloadState == DownloadState.FAILED -> stringResource(R.string.download_failed_short)
        book.finished == true -> stringResource(R.string.finished)
        (book.percent ?: 0.0) > 0 -> book.pageCount?.let { pages ->
            stringResource(R.string.page_of, ((book.percent ?: 0.0) / 100 * pages).toInt().coerceIn(1, pages), pages)
        } ?: stringResource(R.string.read_percent, (book.percent ?: 0.0).toInt())
        else -> return parts.joinToString(" · ")
    }
    return parts.joinToString(" · ")
}

/**
 * A book in a series' list (the 2.4 look): its cover, its number and title, how it is (a "Läst"
 * badge, a progress line while it is being read), its download, and its own actions at the end
 * ([trailing]). A long press starts choosing several.
 */
@OptIn(ExperimentalFoundationApi::class)
@Composable
fun BookLine(
    book: BookRow,
    selecting: Boolean,
    selected: Boolean,
    onClick: () -> Unit,
    onLongClick: () -> Unit,
    modifier: Modifier = Modifier,
    trailing: @Composable () -> Unit = {},
) {
    val colors = KodexTheme.colors
    val reading = book.finished != true && (book.percent ?: 0.0) > 0
    Row(
        modifier
            .fillMaxWidth()
            .heightIn(min = 76.dp)
            .padding(horizontal = 12.dp, vertical = 4.dp)
            .clip(MaterialTheme.shapes.medium)
            .background(if (selected) colors.accentSoft else if (reading) colors.surface2 else colors.surface1)
            .combinedClickable(onClick = onClick, onLongClick = onLongClick)
            .padding(start = 10.dp, end = 2.dp, top = 8.dp, bottom = 8.dp)
            .testTag("book-${book.id}"),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        if (selecting) {
            Checkbox(checked = selected, onCheckedChange = { onClick() }, modifier = Modifier.size(30.dp))
        }
        Cover(book.id, width = 44.dp, corner = 6.dp)
        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(3.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                val number = numberLabel(book.number, book.editionType, book.libraryType)
                Text(
                    if (number == null || mentions(book.title, book.number)) book.title else "$number: ${book.title}",
                    style = MaterialTheme.typography.titleMedium,
                    color = when {
                        book.finished == true -> colors.textMuted
                        reading -> colors.accentText
                        else -> colors.text
                    },
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                    modifier = Modifier.weight(1f, fill = false),
                )
                when {
                    reading -> StateBadge(stringResource(R.string.reading), colors.accentText, colors.accentSoft)
                    book.finished == true -> StateBadge(stringResource(R.string.finished), colors.offlineText, colors.offlineSoft, Icons.Filled.Check)
                }
            }
            Text(bookState(book), style = MaterialTheme.typography.bodySmall, color = colors.textMuted, maxLines = 1,
                overflow = TextOverflow.Ellipsis)
            if (reading) ProgressStrip(((book.percent ?: 0.0) / 100).toFloat(), Modifier.padding(top = 2.dp, end = 8.dp), track = colors.surface3)
        }
        trailing()
    }
}

/** A small rounded badge in a row: "Läser", "✓ Läst". */
@Composable
fun StateBadge(text: String, ink: androidx.compose.ui.graphics.Color, fill: androidx.compose.ui.graphics.Color,
    icon: androidx.compose.ui.graphics.vector.ImageVector? = null) {
    Row(
        Modifier.clip(RoundedCornerShape(8.dp)).background(fill).padding(horizontal = 7.dp, vertical = 2.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(3.dp),
    ) {
        icon?.let { Icon(it, contentDescription = null, tint = ink, modifier = Modifier.size(12.dp)) }
        Text(text, style = MaterialTheme.typography.labelMedium, color = ink, maxLines = 1)
    }
}

/** Whether a title already says its number ("Kapitel 40: …", "Serie 043"), so it isn't put in front again. */
fun mentions(title: String, number: Double?): Boolean {
    number ?: return false
    val text = if (number % 1.0 == 0.0) number.toLong().toString() else number.toString()
    return Regex("(?<![\\d.])0*" + Regex.escape(text) + "(?![\\d])").containsMatchIn(title)
}
