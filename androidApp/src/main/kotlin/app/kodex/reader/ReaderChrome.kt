package app.kodex.reader

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawing
import androidx.compose.foundation.layout.windowInsetsPadding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.SwapHoriz
import androidx.compose.material.icons.filled.SwapVert
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Slider
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import app.kodex.R
import app.kodex.data.ImageMode

private val Scrim = Color(0xD9000000)

/** The reader's bars: back and the title on top; where in the book, and how to read it, below. */
@Composable
fun ReaderChrome(
    title: String,
    page: Int,
    count: Int,
    mode: ImageMode?,
    onMode: (ImageMode) -> Unit,
    onSeek: (Int) -> Unit,
    onClose: () -> Unit,
    extra: @Composable () -> Unit = {},
) {
    Box(Modifier.fillMaxSize().testTag("reader-chrome")) {
        TopBar(title, onClose, Modifier.align(Alignment.TopCenter))
        Column(
            Modifier.align(Alignment.BottomCenter).fillMaxWidth().background(Scrim)
                .windowInsetsPadding(WindowInsets.safeDrawing).padding(horizontal = 16.dp, vertical = 8.dp),
        ) {
            if (count > 1) {
                var dragging by remember(page) { mutableFloatStateOf(page.toFloat()) }
                Text(stringResource(R.string.reader_page_of, dragging.toInt() + 1, count), color = Color.White,
                    style = MaterialTheme.typography.labelLarge)
                Slider(
                    value = dragging,
                    onValueChange = { dragging = it },
                    onValueChangeFinished = { onSeek(dragging.toInt()) },
                    valueRange = 0f..(count - 1).toFloat(),
                    modifier = Modifier.testTag("reader-slider"),
                )
            }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
                if (mode != null) {
                    ModeChip(stringResource(R.string.mode_ltr), mode == ImageMode.PAGED_LTR, Icons.Filled.SwapHoriz) { onMode(ImageMode.PAGED_LTR) }
                    ModeChip(stringResource(R.string.mode_rtl), mode == ImageMode.PAGED_RTL, Icons.Filled.SwapHoriz) { onMode(ImageMode.PAGED_RTL) }
                    ModeChip(stringResource(R.string.mode_vertical), mode == ImageMode.VERTICAL, Icons.Filled.SwapVert) { onMode(ImageMode.VERTICAL) }
                }
                extra()
            }
        }
    }
}

@Composable
fun TopBar(title: String, onClose: () -> Unit, modifier: Modifier = Modifier) {
    Row(
        modifier.fillMaxWidth().background(Scrim).windowInsetsPadding(WindowInsets.safeDrawing).padding(4.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        IconButton(onClick = onClose) {
            Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = stringResource(R.string.back), tint = Color.White)
        }
        Text(title, color = Color.White, maxLines = 1, overflow = TextOverflow.Ellipsis, style = MaterialTheme.typography.titleMedium)
    }
}

@Composable
private fun ModeChip(label: String, selected: Boolean, icon: androidx.compose.ui.graphics.vector.ImageVector, onClick: () -> Unit) {
    FilterChip(
        selected = selected,
        onClick = onClick,
        label = { Text(label) },
        leadingIcon = { Icon(icon, contentDescription = null) },
    )
}
