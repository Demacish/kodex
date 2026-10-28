package app.kodex.ui.downloads

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.ListItem
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import app.kodex.R
import app.kodex.data.db.DownloadKinds
import app.kodex.data.db.DownloadState
import app.kodex.data.db.KodexDatabase
import app.kodex.download.Downloads
import app.kodex.ui.AppViewModel
import app.kodex.ui.BookKey
import app.kodex.ui.Navigator
import app.kodex.ui.components.Bar
import app.kodex.ui.components.Cover
import app.kodex.ui.components.Empty
import app.kodex.ui.components.clickableRow
import app.kodex.ui.components.size
import kotlinx.coroutines.launch
import org.koin.compose.koinInject

/** Nedladdat: what is on the device, what is on its way, and how much room it takes. */
@Composable
fun DownloadsScreen(app: AppViewModel, navigator: Navigator) {
    val db: KodexDatabase = koinInject()
    val downloads: Downloads = koinInject()
    val scope = rememberCoroutineScope()
    val rows by db.downloads().list().collectAsStateWithLifecycle(initialValue = emptyList())
    val used by app.usedBytes.collectAsStateWithLifecycle(initialValue = 0L)
    Scaffold(topBar = { Bar(stringResource(R.string.tab_downloads)) }) { padding ->
        if (rows.isEmpty()) {
            Empty(stringResource(R.string.downloads_empty), Modifier.padding(padding))
            return@Scaffold
        }
        LazyColumn(Modifier.fillMaxSize().testTag("downloads"), contentPadding = padding) {
            item {
                Text(
                    stringResource(R.string.downloads_used, size(used)),
                    style = MaterialTheme.typography.bodyMedium,
                    modifier = Modifier.padding(horizontal = 16.dp, vertical = 8.dp),
                )
            }
            items(rows, key = { it.bookId }) { row ->
                ListItem(
                    modifier = Modifier.clickableRow { navigator.open(BookKey(row.bookId)) }.testTag("download-${row.bookId}"),
                    leadingContent = { Cover(row.bookId) },
                    headlineContent = { Text(row.title, maxLines = 2, overflow = TextOverflow.Ellipsis) },
                    supportingContent = {
                        Column {
                            val state = when (row.state) {
                                DownloadState.DONE -> stringResource(
                                    if (row.kind == DownloadKinds.FILE) R.string.downloaded_verified else R.string.downloaded_pages,
                                    size(row.bytes),
                                )
                                DownloadState.RUNNING -> stringResource(R.string.downloading_size, size(row.bytes), size(row.total))
                                DownloadState.QUEUED -> stringResource(R.string.download_waiting, size(row.bytes), size(row.total))
                                DownloadState.FAILED -> stringResource(R.string.download_failed, row.error.orEmpty())
                            }
                            Text(state, style = MaterialTheme.typography.bodySmall)
                            if (row.automatic) Text(stringResource(R.string.download_automatic), style = MaterialTheme.typography.bodySmall)
                            if (row.state == DownloadState.RUNNING && row.total > 0) {
                                LinearProgressIndicator(
                                    progress = { (row.bytes.toFloat() / row.total).coerceIn(0f, 1f) },
                                    modifier = Modifier.fillMaxWidth(),
                                )
                            }
                        }
                    },
                    trailingContent = {
                        IconButton(onClick = { scope.launch { downloads.remove(row.bookId) } }) {
                            Icon(Icons.Filled.Delete, contentDescription = stringResource(R.string.remove_download))
                        }
                    },
                )
            }
        }
    }
}
