package app.kodex.ui

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.DownloadForOffline
import androidx.compose.material.icons.filled.Explore
import androidx.compose.material.icons.filled.LocalLibrary
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material3.Badge
import androidx.compose.material3.BadgedBox
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.material3.adaptive.ExperimentalMaterial3AdaptiveApi
import androidx.compose.material3.adaptive.navigation3.ListDetailSceneStrategy
import androidx.compose.material3.adaptive.navigation3.rememberListDetailSceneStrategy
import androidx.compose.material3.adaptive.navigationsuite.NavigationSuiteScaffold
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.getValue
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.navigation3.rememberViewModelStoreNavEntryDecorator
import androidx.navigation3.runtime.NavKey
import androidx.navigation3.runtime.entryProvider
import androidx.navigation3.runtime.rememberNavBackStack
import androidx.navigation3.runtime.rememberSaveableStateHolderNavEntryDecorator
import androidx.navigation3.ui.NavDisplay
import app.kodex.R
import app.kodex.account.Session
import app.kodex.reader.ReaderActivity
import app.kodex.ui.discover.DiscoverScreen
import app.kodex.ui.downloads.DownloadsScreen
import app.kodex.ui.library.BookScreen
import app.kodex.ui.library.CollectionScreen
import app.kodex.ui.library.LibraryHome
import app.kodex.ui.library.SeriesScreen
import app.kodex.ui.login.LoginScreen
import app.kodex.ui.login.LoginViewModel
import app.kodex.ui.settings.SettingsScreen
import app.kodex.ui.theme.KodexTheme
import kotlinx.serialization.Serializable
import org.koin.compose.viewmodel.koinViewModel

@Serializable data object LibraryHomeKey : NavKey

@Serializable data class SeriesKey(val id: Int) : NavKey

@Serializable data class BookKey(val id: Int) : NavKey

@Serializable data class CollectionKey(val id: Int, val name: String) : NavKey

@Serializable data object DiscoverKey : NavKey

@Serializable data object DownloadsKey : NavKey

@Serializable data object SettingsKey : NavKey

enum class Tab(val key: NavKey, val label: Int, val icon: ImageVector) {
    LIBRARY(LibraryHomeKey, R.string.tab_library, Icons.Filled.LocalLibrary),
    DISCOVER(DiscoverKey, R.string.tab_discover, Icons.Filled.Explore),
    DOWNLOADS(DownloadsKey, R.string.tab_downloads, Icons.Filled.DownloadForOffline),
    SETTINGS(SettingsKey, R.string.tab_settings, Icons.Filled.Settings),
}

/** The logged-in account, for covers from the server (they need its key). */
val LocalSession = staticCompositionLocalOf<Session?> { null }

/** Where the screens go: one place, so every screen navigates the same way. */
class Navigator(private val stack: MutableList<NavKey>, private val openReader: (Int, String?, String?) -> Unit) {
    fun open(key: NavKey) {
        stack.add(key)
    }

    /** The reader, at the book's position or at [position] (a bookmark's, of [kind]). */
    fun read(bookId: Int, position: String? = null, kind: String? = null) = openReader(bookId, position, kind)

    fun back() {
        if (stack.size > 1) stack.removeAt(stack.lastIndex)
    }
}

@OptIn(ExperimentalMaterial3AdaptiveApi::class)
@Composable
fun KodexAppUi(login: LoginViewModel) {
    val app: AppViewModel = koinViewModel()
    val session by app.session.collectAsStateWithLifecycle()
    val settings by app.settings.collectAsStateWithLifecycle()
    KodexTheme(settings.theme, settings.accent) {
        when (val state = session) {
            SessionState.Loading -> Box(Modifier.fillMaxSize()) { CircularProgressIndicator(Modifier.align(Alignment.Center)) }
            SessionState.LoggedOut -> LoginScreen(login)
            is SessionState.LoggedIn -> CompositionLocalProvider(LocalSession provides state.session) { Shell(app) }
        }
    }
}

/**
 * The tabs around a screen: a bar at the foot of a phone, a rail down the side of a tablet.
 * [badge] marks a tab (downloads on their way).
 */
@Composable
fun ShellFrame(tab: Tab, onTab: (Tab) -> Unit, badge: (Tab) -> Boolean = { false }, content: @Composable () -> Unit) {
    val colors = KodexTheme.colors
    NavigationSuiteScaffold(
        navigationSuiteItems = {
            Tab.entries.forEach { item ->
                item(
                    selected = item == tab,
                    onClick = { onTab(item) },
                    icon = {
                        BadgedBox(badge = { if (badge(item)) Badge(containerColor = colors.offline) }) {
                            Icon(item.icon, contentDescription = null)
                        }
                    },
                    label = { Text(stringResource(item.label)) },
                    modifier = Modifier.testTag("tab-${item.name.lowercase()}"),
                )
            }
        },
        containerColor = colors.background,
    ) {
        content()
    }
}

@OptIn(ExperimentalMaterial3AdaptiveApi::class)
@Composable
private fun Shell(app: AppViewModel) {
    val context = LocalContext.current
    val stack = rememberNavBackStack(LibraryHomeKey)
    val navigator = Navigator(stack) { id, position, kind -> context.startActivity(ReaderActivity.intent(context, id, position, kind)) }
    val current = stack.lastOrNull()
    val tab = Tab.entries.lastOrNull { tab -> stack.any { it == tab.key } } ?: Tab.LIBRARY
    val listDetail = rememberListDetailSceneStrategy<NavKey>()
    val active by app.activeDownloads.collectAsStateWithLifecycle(initialValue = 0)
    ShellFrame(
        tab,
        onTab = { item ->
            if (current != item.key) {
                stack.clear()
                stack.add(item.key)
            }
        },
        badge = { it == Tab.DOWNLOADS && active > 0 },
    ) {
        NavDisplay(
            backStack = stack,
            onBack = { navigator.back() },
            entryDecorators = listOf(rememberSaveableStateHolderNavEntryDecorator(), rememberViewModelStoreNavEntryDecorator()),
            sceneStrategies = listOf(listDetail),
            entryProvider = entryProvider {
                entry<LibraryHomeKey> { LibraryHome(navigator, app) }
                entry<DiscoverKey> { DiscoverScreen(navigator, app) }
                entry<SeriesKey>(metadata = ListDetailSceneStrategy.listPane()) { SeriesScreen(it.id, navigator, app) }
                entry<CollectionKey>(metadata = ListDetailSceneStrategy.listPane()) { CollectionScreen(it.id, it.name, navigator, app) }
                entry<BookKey>(metadata = ListDetailSceneStrategy.detailPane()) { BookScreen(it.id, navigator, app) }
                entry<DownloadsKey> { DownloadsScreen(app, navigator) }
                entry<SettingsKey> { SettingsScreen(app) }
            },
        )
    }
}
