package app.kodex.ui

import android.content.Context
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import androidx.room3.withWriteTransaction
import app.kodex.account.AccountStore
import app.kodex.account.Session
import app.kodex.data.AppSettings
import app.kodex.data.SettingsStore
import app.kodex.data.StorageTarget
import app.kodex.data.db.DownloadState
import app.kodex.data.db.KodexDatabase
import app.kodex.download.Downloads
import app.kodex.sync.ApiProvider
import app.kodex.sync.SyncProblems
import app.kodex.sync.SyncStatus
import app.kodex.sync.SyncWorker
import app.kodex.widget.ContinueReadingWidget
import coil3.SingletonImageLoader
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch

sealed interface SessionState {
    data object Loading : SessionState

    data object LoggedOut : SessionState

    data class LoggedIn(val session: Session) : SessionState
}

class AppViewModel(
    private val context: Context,
    private val accounts: AccountStore,
    private val settingsStore: SettingsStore,
    private val downloads: Downloads,
    private val db: KodexDatabase,
    private val apis: ApiProvider,
    private val problems: SyncProblems,
) : ViewModel() {
    val session: StateFlow<SessionState> = accounts.session
        .map { if (it == null) SessionState.LoggedOut else SessionState.LoggedIn(it) }
        .stateIn(viewModelScope, SharingStarted.Eagerly, SessionState.Loading)

    val settings: StateFlow<AppSettings> = settingsStore.settings.stateIn(viewModelScope, SharingStarted.Eagerly, AppSettings())

    val syncState = db.state().observe()

    val syncStatus: Flow<SyncStatus> = SyncWorker.status(context, problems)

    val pending = db.state().pendingCount()

    val usedBytes = db.downloads().usedBytes()

    /** Downloads waiting or running, for the tab's mark. */
    val activeDownloads: Flow<Int> = db.downloads().list()
        .map { rows -> rows.count { it.state == DownloadState.QUEUED || it.state == DownloadState.RUNNING } }

    val counts = db.catalog().counts()

    /** Whether the device has a memory card to download to. */
    val cardAvailable: Boolean get() = downloads.card() != null

    fun freeBytes(target: StorageTarget): Long? = downloads.freeBytes(target)

    /** The covers and pages kept to show them faster (and covers offline); null until measured. */
    val cacheBytes = MutableStateFlow<Long?>(null)

    fun syncNow() = SyncWorker.now(context)

    fun update(change: (AppSettings) -> AppSettings) {
        viewModelScope.launch {
            val before = settingsStore.current()
            settingsStore.update(change)
            val after = settingsStore.current()
            // Waiting downloads take the new network rule, or the new number at once.
            if (after.wifiOnly != before.wifiOnly || after.concurrency != before.concurrency) downloads.requeueAll()
            if (after.cleanupDays != before.cleanupDays) downloads.cleanUp()
        }
    }

    fun measureCache() {
        viewModelScope.launch(Dispatchers.IO) {
            cacheBytes.value = context.cacheDir.walkBottomUp().filter { it.isFile }.sumOf { it.length() }
        }
    }

    /** Empties the cache; covers come again from the server when they are next shown. */
    fun clearCache() {
        viewModelScope.launch(Dispatchers.IO) {
            val images = SingletonImageLoader.get(context)
            images.memoryCache?.clear()
            images.diskCache?.clear()
            // Coil's own folder stays, emptied: it keeps its journal there.
            context.cacheDir.listFiles()?.filter { it.name != "image_cache" }?.forEach { it.deleteRecursively() }
            cacheBytes.value = context.cacheDir.walkBottomUp().filter { it.isFile }.sumOf { it.length() }
        }
    }

    /** Revokes the app's key, then forgets the account, its catalog and its downloads. */
    fun logout() {
        viewModelScope.launch {
            accounts.current()?.let { session -> runCatching { apis.api(session).logout() } }
            SyncWorker.cancel(context)
            problems.clear()
            wipe(db, downloads)
            accounts.forget()
            ContinueReadingWidget.refresh(context)
        }
    }
}

/** Everything the device has for an account: its catalog, positions and downloads. */
suspend fun wipe(db: KodexDatabase, downloads: Downloads) {
    downloads.clearAll()
    db.withWriteTransaction {
        db.catalog().apply {
            clearAllCollectionBooks()
            clearCollections()
            clearBooks()
            clearSeries()
            clearLibraries()
            clearProgress()
        }
        db.state().clearOutbox()
        db.state().clearState()
        db.bookmarks().clearAll()
    }
}
