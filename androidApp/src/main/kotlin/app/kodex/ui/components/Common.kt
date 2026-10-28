package app.kodex.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.DownloadDone
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.ListItem
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import app.kodex.R
import app.kodex.data.db.BookRow
import app.kodex.data.db.DownloadState
import app.kodex.ui.LocalSession
import coil3.compose.AsyncImage
import coil3.compose.LocalPlatformContext
import coil3.network.NetworkHeaders
import coil3.network.httpHeaders
import coil3.request.ImageRequest
import java.util.Locale

/** A book's cover from the server (kept in Coil's disk cache, so it shows offline too). */
@Composable
fun Cover(bookId: Int?, modifier: Modifier = Modifier, width: Dp = 56.dp) {
    val session = LocalSession.current
    val context = LocalPlatformContext.current
    Box(
        modifier.width(width).aspectRatio(2f / 3f).clip(RoundedCornerShape(6.dp)).background(MaterialTheme.colorScheme.surfaceVariant),
    ) {
        if (bookId != null && session != null) {
            val request = remember(bookId, session) {
                ImageRequest.Builder(context)
                    .data("${session.server}/api/books/$bookId/cover?size=${if (width > 96.dp) "medium" else "small"}")
                    .httpHeaders(NetworkHeaders.Builder().set("Authorization", "Bearer ${session.key}").build())
                    .build()
            }
            AsyncImage(request, contentDescription = null, contentScale = ContentScale.Crop, modifier = Modifier.fillMaxSize())
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun Bar(title: String, onBack: (() -> Unit)? = null, actions: @Composable () -> Unit = {}) {
    TopAppBar(
        title = { Text(title, maxLines = 1, overflow = TextOverflow.Ellipsis) },
        navigationIcon = {
            if (onBack != null) {
                IconButton(onClick = onBack) { Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = stringResource(R.string.back)) }
            }
        },
        actions = { actions() },
    )
}

@Composable
fun BookListItem(book: BookRow, onClick: () -> Unit) {
    ListItem(
        modifier = Modifier.fillMaxWidth().testTag("book-${book.id}").clickableRow(onClick),
        leadingContent = { Cover(book.id) },
        headlineContent = { Text(book.title, maxLines = 2, overflow = TextOverflow.Ellipsis) },
        supportingContent = {
            Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                Text(details(book.format, book.pageCount, book.fileSize), style = MaterialTheme.typography.bodySmall)
                val percent = book.percent
                if (percent != null && percent > 0 && book.finished != true) {
                    LinearProgressIndicator(progress = { (percent / 100).toFloat() }, modifier = Modifier.fillMaxWidth(0.6f))
                }
            }
        },
        trailingContent = {
            Row(horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                if (book.downloadState == DownloadState.DONE) {
                    Icon(Icons.Filled.DownloadDone, contentDescription = stringResource(R.string.downloaded))
                }
                if (book.finished == true) Icon(Icons.Filled.CheckCircle, contentDescription = stringResource(R.string.finished))
            }
        },
    )
}

@Composable
fun Empty(text: String, modifier: Modifier = Modifier) {
    Box(modifier.fillMaxSize().padding(32.dp), contentAlignment = Alignment.Center) {
        Text(text, textAlign = TextAlign.Center, style = MaterialTheme.typography.bodyLarge, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

@Composable
fun details(format: String, pages: Int?, bytes: Long): String =
    listOfNotNull(format.uppercase(Locale.ROOT), pages?.let { stringResource(R.string.pages_count, it) }, size(bytes)).joinToString(" · ")

fun size(bytes: Long): String = when {
    bytes >= 1_000_000_000 -> String.format(Locale.getDefault(), "%.1f GB", bytes / 1e9)
    bytes >= 1_000_000 -> String.format(Locale.getDefault(), "%.0f MB", bytes / 1e6)
    else -> String.format(Locale.getDefault(), "%.0f kB", bytes / 1e3)
}

fun Modifier.clickableRow(onClick: () -> Unit): Modifier = clickable(onClick = onClick)
