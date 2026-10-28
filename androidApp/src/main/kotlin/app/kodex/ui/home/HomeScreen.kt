package app.kodex.ui.home

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.ListItem
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import app.kodex.R
import app.kodex.ui.CollectionKey
import app.kodex.ui.Navigator
import app.kodex.ui.components.Bar
import app.kodex.ui.components.Cover
import app.kodex.ui.components.Empty
import app.kodex.ui.components.clickableRow
import app.kodex.ui.library.LibraryViewModel
import org.koin.compose.viewmodel.koinViewModel

/** Läs: where the user left off, on any device, and the collections. */
@Composable
fun HomeScreen(navigator: Navigator) {
    val library: LibraryViewModel = koinViewModel()
    val reading by library.continueReading.collectAsStateWithLifecycle(initialValue = emptyList())
    val collections by library.collections.collectAsStateWithLifecycle(initialValue = emptyList())
    Scaffold(topBar = { Bar(stringResource(R.string.tab_home)) }) { padding ->
        if (reading.isEmpty() && collections.isEmpty()) {
            Empty(stringResource(R.string.home_empty), Modifier.padding(padding))
            return@Scaffold
        }
        LazyColumn(Modifier.fillMaxSize().testTag("home"), contentPadding = padding) {
            if (reading.isNotEmpty()) {
                item { Heading(stringResource(R.string.continue_reading)) }
                item {
                    LazyRow(contentPadding = PaddingValues(horizontal = 16.dp), horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                        items(reading, key = { it.id }) { book ->
                            Column(Modifier.width(120.dp).clickableRow { navigator.read(book.id) }.testTag("continue-${book.id}")) {
                                Cover(book.id, width = 120.dp)
                                LinearProgressIndicator(progress = { (book.percent / 100).toFloat() }, modifier = Modifier.fillMaxWidth().padding(top = 6.dp))
                                Text(book.title, maxLines = 2, overflow = TextOverflow.Ellipsis, style = MaterialTheme.typography.bodyMedium)
                                book.seriesTitle?.let {
                                    Text(it, maxLines = 1, overflow = TextOverflow.Ellipsis, style = MaterialTheme.typography.bodySmall)
                                }
                            }
                        }
                    }
                }
            }
            if (collections.isNotEmpty()) {
                item { Heading(stringResource(R.string.collections)) }
                items(collections, key = { it.id }) { collection ->
                    ListItem(
                        headlineContent = { Text(collection.name) },
                        modifier = Modifier.clickableRow { navigator.open(CollectionKey(collection.id, collection.name)) },
                    )
                }
            }
        }
    }
}

@Composable
private fun Heading(text: String) {
    Text(text, style = MaterialTheme.typography.titleMedium, modifier = Modifier.padding(start = 16.dp, top = 16.dp, bottom = 8.dp))
}
