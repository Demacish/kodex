package app.kodex.ui

import android.content.Context
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import androidx.room3.withWriteTransaction
import app.kodex.account.AccountStore
import app.kodex.account.Session
import app.kodex.data.AppSettings
import app.kodex.data.SettingsStore
import app.kodex.data.db.KodexDatabase
import app.kodex.download.Downloads
import app.kodex.sync.ApiProvider
import app.kodex.sync.SyncWorker
import app.kodex.widget.ContinueReadingWidget
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
) : ViewModel() {
    val session: StateFlow<SessionState> = accounts.session
        .map { if (it == null) SessionState.LoggedOut else SessionState.LoggedIn(it) }
        .stateIn(viewModelScope, SharingStarted.Eagerly, SessionState.Loading)

    val settings: StateFlow<AppSettings> = settingsStore.settings.stateIn(viewModelScope, SharingStarted.Eagerly, AppSettings())

    val syncState = db.state().observe()

    val pending = db.state().pendingCount()

    val usedBytes = db.downloads().usedBytes()

    fun syncNow() = SyncWorker.now(context)

    fun update(change: (AppSettings) -> AppSettings) {
        viewModelScope.launch {
            val before = settingsStore.current()
            settingsStore.update(change)
            if (settingsStore.current().wifiOnly != before.wifiOnly) downloads.requeueAll()
        }
    }

    /** Revokes the app's key, then forgets the account, its catalog and its downloads. */
    fun logout() {
        viewModelScope.launch {
            accounts.current()?.let { session -> runCatching { apis.api(session).logout() } }
            SyncWorker.cancel(context)
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
    }
}
