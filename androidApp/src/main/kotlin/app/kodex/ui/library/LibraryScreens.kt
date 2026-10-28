package app.kodex.ui.library

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.GridItemSpan
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Search
import androidx.compose.material3.Icon
import androidx.compose.material3.ListItem
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.foundation.layout.Column
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import app.kodex.R
import app.kodex.ui.BookKey
import app.kodex.ui.LibraryKey
import app.kodex.ui.Navigator
import app.kodex.ui.SeriesKey
import app.kodex.ui.components.Bar
import app.kodex.ui.components.BookListItem
import app.kodex.ui.components.Cover
import app.kodex.ui.components.Empty
import app.kodex.ui.components.clickableRow
import org.koin.compose.viewmodel.koinViewModel

/** Bibliotek: the libraries, and a search over every book on the device. */
@Composable
fun LibrariesScreen(navigator: Navigator) {
    val vm: LibraryViewModel = koinViewModel()
    val libraries by vm.libraries.collectAsStateWithLifecycle(initialValue = emptyList())
    val query by vm.query.collectAsStateWithLifecycle()
    val results by vm.results.collectAsStateWithLifecycle(initialValue = emptyList())
    Scaffold(topBar = { Bar(stringResource(R.string.tab_library)) }) { padding ->
        LazyColumn(Modifier.fillMaxSize().testTag("libraries"), contentPadding = padding) {
            item {
                OutlinedTextField(
                    value = query,
                    onValueChange = { vm.query.value = it },
                    leadingIcon = { Icon(Icons.Filled.Search, contentDescription = null) },
                    placeholder = { Text(stringResource(R.string.search_books)) },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 8.dp).testTag("search"),
                )
            }
            if (query.isNotBlank()) {
                items(results, key = { "b${it.id}" }) { BookListItem(it) { navigator.open(BookKey(it.id)) } }
            } else {
                items(libraries, key = { it.id }) { library ->
                    ListItem(
                        headlineContent = { Text(library.name) },
                        modifier = Modifier.clickableRow { navigator.open(LibraryKey(library.id, library.name)) }.testTag("library-${library.id}"),
                    )
                }
            }
        }
        if (libraries.isEmpty() && query.isBlank()) Empty(stringResource(R.string.library_empty), Modifier.padding(padding))
    }
}

/** A library's series as covers, and its books outside any series. */
@Composable
fun LibraryScreen(libraryId: Int, name: String, navigator: Navigator) {
    val vm: LibraryViewModel = koinViewModel()
    val series by remember(libraryId) { vm.series(libraryId) }.collectAsStateWithLifecycle(initialValue = emptyList())
    val loose by remember(libraryId) { vm.looseBooks(libraryId) }.collectAsStateWithLifecycle(initialValue = emptyList())
    Scaffold(topBar = { Bar(name, onBack = navigator::back) }) { padding ->
        LazyVerticalGrid(
            columns = GridCells.Adaptive(120.dp),
            contentPadding = PaddingValues(16.dp, padding.calculateTopPadding() + 8.dp, 16.dp, padding.calculateBottomPadding() + 16.dp),
            horizontalArrangement = Arrangement.spacedBy(12.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp),
            modifier = Modifier.fillMaxSize().testTag("series-grid"),
        ) {
            items(series, key = { it.id }) { item ->
                Column(Modifier.clickableRow { navigator.open(SeriesKey(item.id)) }.testTag("series-${item.id}")) {
                    Cover(item.firstBookId, width = 120.dp)
                    Text(item.title, maxLines = 2, overflow = TextOverflow.Ellipsis, style = MaterialTheme.typography.bodyMedium)
                    Text(
                        stringResource(R.string.series_read, item.readCount, item.bookCount),
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
            items(loose, key = { "b${it.id}" }, span = { GridItemSpan(maxLineSpan) }) { BookListItem(it) { navigator.open(BookKey(it.id)) } }
        }
        if (series.isEmpty() && loose.isEmpty()) Empty(stringResource(R.string.library_nothing), Modifier.padding(padding))
    }
}

@Composable
fun SeriesScreen(seriesId: Int, navigator: Navigator) {
    val vm: LibraryViewModel = koinViewModel()
    val series by remember(seriesId) { vm.seriesInfo(seriesId) }.collectAsStateWithLifecycle(initialValue = null)
    val books by remember(seriesId) { vm.books(seriesId) }.collectAsStateWithLifecycle(initialValue = emptyList())
    Scaffold(topBar = { Bar(series?.title.orEmpty(), onBack = navigator::back) }) { padding ->
        LazyColumn(Modifier.fillMaxSize().testTag("series"), contentPadding = padding) {
            series?.summary?.takeIf { it.isNotBlank() }?.let { summary ->
                item {
                    Text(
                        summary,
                        style = MaterialTheme.typography.bodyMedium,
                        maxLines = 6,
                        overflow = TextOverflow.Ellipsis,
                        modifier = Modifier.padding(16.dp),
                    )
                }
            }
            items(books, key = { it.id }) { BookListItem(it) { navigator.open(BookKey(it.id)) } }
        }
    }
}

@Composable
fun CollectionScreen(collectionId: Int, name: String, navigator: Navigator) {
    val vm: LibraryViewModel = koinViewModel()
    val books by remember(collectionId) { vm.collectionBooks(collectionId) }.collectAsStateWithLifecycle(initialValue = emptyList())
    Scaffold(topBar = { Bar(name, onBack = navigator::back) }) { padding ->
        Box(Modifier.padding(padding)) {
            if (books.isEmpty()) Empty(stringResource(R.string.collection_empty))
            LazyColumn(Modifier.fillMaxSize()) { items(books, key = { it.id }) { BookListItem(it) { navigator.open(BookKey(it.id)) } } }
        }
    }
}
