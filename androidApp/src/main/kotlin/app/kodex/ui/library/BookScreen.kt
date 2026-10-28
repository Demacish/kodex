package app.kodex.ui.library

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.MenuBook
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Download
import androidx.compose.material3.Button
import androidx.compose.material3.Icon
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import app.kodex.R
import app.kodex.data.db.DownloadState
import app.kodex.download.FILE_FORMATS
import app.kodex.ui.Navigator
import app.kodex.ui.components.Bar
import app.kodex.ui.components.Cover
import app.kodex.ui.components.details
import app.kodex.ui.components.size
import org.koin.compose.viewmodel.koinViewModel
import org.koin.core.parameter.parametersOf

@OptIn(ExperimentalLayoutApi::class)
@Composable
fun BookScreen(bookId: Int, navigator: Navigator) {
    val vm: BookViewModel = koinViewModel(key = "book-$bookId") { parametersOf(bookId) }
    val book by vm.book.collectAsStateWithLifecycle(initialValue = null)
    val progress by vm.progress.collectAsStateWithLifecycle(initialValue = null)
    val download by vm.download.collectAsStateWithLifecycle(initialValue = null)
    val current = book
    Scaffold(topBar = { Bar(current?.title.orEmpty(), onBack = navigator::back) }) { padding ->
        if (current == null) return@Scaffold
        Column(
            Modifier.fillMaxSize().padding(padding).verticalScroll(rememberScrollState()).padding(16.dp).testTag("book"),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Row(horizontalArrangement = Arrangement.spacedBy(16.dp)) {
                Cover(current.id, width = 120.dp)
                Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                    Text(current.title, style = MaterialTheme.typography.titleLarge)
                    if (current.authors.isNotBlank()) Text(current.authors, style = MaterialTheme.typography.bodyMedium)
                    Text(details(current.format, current.pageCount, current.fileSize), style = MaterialTheme.typography.bodySmall)
                    current.publishedYear?.let { Text(it.toString(), style = MaterialTheme.typography.bodySmall) }
                }
            }
            val percent = progress?.percent ?: 0.0
            val finished = progress?.finished == true
            if (percent > 0 || finished) {
                LinearProgressIndicator(progress = { (if (finished) 1.0 else percent / 100).toFloat() }, modifier = Modifier.fillMaxWidth())
                Text(
                    if (finished) stringResource(R.string.finished) else stringResource(R.string.read_percent, percent.toInt()),
                    style = MaterialTheme.typography.bodySmall,
                )
            }
            val downloaded = download?.state == DownloadState.DONE
            val canRead = downloaded || current.format !in FILE_FORMATS || current.format == "cbz"
            FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(onClick = { navigator.read(current.id) }, enabled = canRead, modifier = Modifier.testTag("read")) {
                    Icon(Icons.AutoMirrored.Filled.MenuBook, contentDescription = null)
                    Text(stringResource(if (percent > 0 && !finished) R.string.continue_reading else R.string.read), Modifier.padding(start = 8.dp))
                }
                when (download?.state) {
                    DownloadState.DONE -> OutlinedButton(onClick = vm::removeDownload, modifier = Modifier.testTag("remove-download")) {
                        Icon(Icons.Filled.Delete, contentDescription = null)
                        Text(stringResource(R.string.remove_download), Modifier.padding(start = 8.dp))
                    }
                    DownloadState.QUEUED, DownloadState.RUNNING -> OutlinedButton(onClick = vm::removeDownload) {
                        Text(stringResource(R.string.cancel_download))
                    }
                    else -> OutlinedButton(onClick = vm::download, modifier = Modifier.testTag("download")) {
                        Icon(Icons.Filled.Download, contentDescription = null)
                        Text(stringResource(R.string.download), Modifier.padding(start = 8.dp))
                    }
                }
                TextButton(onClick = { vm.markRead(!finished) }) {
                    Text(stringResource(if (finished) R.string.mark_unread else R.string.mark_read))
                }
            }
            download?.let { d ->
                when (d.state) {
                    DownloadState.RUNNING, DownloadState.QUEUED -> {
                        val fraction = if (d.total > 0) (d.bytes.toFloat() / d.total).coerceIn(0f, 1f) else 0f
                        LinearProgressIndicator(progress = { fraction }, modifier = Modifier.fillMaxWidth().testTag("download-progress"))
                        Text(
                            stringResource(if (d.state == DownloadState.QUEUED) R.string.download_waiting else R.string.downloading_size,
                                size(d.bytes), size(d.total)),
                            style = MaterialTheme.typography.bodySmall,
                        )
                    }
                    DownloadState.FAILED -> Text(stringResource(R.string.download_failed, d.error.orEmpty()), color = MaterialTheme.colorScheme.error)
                    DownloadState.DONE -> Text(stringResource(R.string.downloaded_size, size(d.bytes)), style = MaterialTheme.typography.bodySmall)
                }
            }
            if (!canRead) Text(stringResource(R.string.download_to_read), style = MaterialTheme.typography.bodySmall)
            current.summary?.takeIf { it.isNotBlank() }?.let { Text(it, style = MaterialTheme.typography.bodyMedium) }
        }
    }
}
