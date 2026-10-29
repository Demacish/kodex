package app.kodex.sync

import android.content.Context
import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.intPreferencesKey
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map

/** Why the last sync of the catalog didn't get through; gone once one does. */
sealed interface SyncProblem {
    /** No answer from the server (no network, or the server is down). */
    data object Unreachable : SyncProblem

    /** The server answered with an error. */
    data class Server(val status: Int, val detail: String) : SyncProblem

    /** The server's answer isn't one this version of the app can read. */
    data object Unreadable : SyncProblem
}

/** A sync under way ([running]), one waiting for a network ([waiting]), and the last [problem]. */
data class SyncStatus(val running: Boolean = false, val waiting: Boolean = false, val problem: SyncProblem? = null) {
    val busy: Boolean get() = running || waiting
}

private val Context.syncData: DataStore<Preferences> by preferencesDataStore("sync")

/** The last [SyncProblem], kept on the device so the app can say why it has nothing new. */
class SyncProblems(private val context: Context) {
    private object Keys {
        val status = intPreferencesKey("problem_status")
        val detail = stringPreferencesKey("problem_detail")
    }

    val problem: Flow<SyncProblem?> = context.syncData.data.map { prefs ->
        when (val status = prefs[Keys.status]) {
            null -> null
            UNREACHABLE -> SyncProblem.Unreachable
            UNREADABLE -> SyncProblem.Unreadable
            else -> SyncProblem.Server(status, prefs[Keys.detail].orEmpty())
        }
    }

    suspend fun record(problem: SyncProblem) {
        context.syncData.edit { prefs ->
            prefs[Keys.status] = when (problem) {
                SyncProblem.Unreachable -> UNREACHABLE
                SyncProblem.Unreadable -> UNREADABLE
                is SyncProblem.Server -> problem.status
            }
            prefs[Keys.detail] = (problem as? SyncProblem.Server)?.detail.orEmpty()
        }
    }

    suspend fun clear() {
        context.syncData.edit { it.clear() }
    }

    private companion object {
        const val UNREACHABLE = -1
        const val UNREADABLE = -2
    }
}
