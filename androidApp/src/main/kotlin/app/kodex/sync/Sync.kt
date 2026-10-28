package app.kodex.sync

import android.content.Context
import androidx.work.BackoffPolicy
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import androidx.work.workDataOf
import app.kodex.BuildConfig
import app.kodex.account.AccountStore
import app.kodex.account.Session
import app.kodex.data.Positions
import app.kodex.data.RoomCatalogStore
import app.kodex.data.db.KodexDatabase
import app.kodex.download.Downloads
import app.kodex.shared.api.KodexApi
import app.kodex.shared.api.KodexApiException
import app.kodex.shared.progress.ProgressSender
import app.kodex.shared.sync.SyncEngine
import app.kodex.widget.ContinueReadingWidget
import io.ktor.client.engine.HttpClientEngine
import io.ktor.client.plugins.UserAgent
import java.io.IOException
import java.util.concurrent.TimeUnit
import kotlinx.coroutines.CancellationException
import org.koin.core.component.KoinComponent
import org.koin.core.component.inject

/** A KodexApi for the logged-in server, kept while the session is the same. */
class ApiProvider(val engine: HttpClientEngine) {
    private var cached: Pair<Session, KodexApi>? = null

    @Synchronized
    fun api(session: Session): KodexApi {
        cached?.let { (known, api) -> if (known == session) return api else api.close() }
        return KodexApi(session.server, { session.key }, engine) {
            install(UserAgent) { agent = "Kodex-Android/${BuildConfig.VERSION_NAME}" }
        }.also { cached = session to it }
    }

    /** For logging in, before there is a session. */
    fun anonymous(server: String): KodexApi = KodexApi(server, { null }, engine) {
        install(UserAgent) { agent = "Kodex-Android/${BuildConfig.VERSION_NAME}" }
    }
}

/**
 * Sends the reading positions read here, brings the catalog up to date, removes downloads of
 * books that are gone, and fetches the next books in the series being read.
 */
class SyncWorker(context: Context, params: WorkerParameters) : CoroutineWorker(context, params), KoinComponent {
    private val db: KodexDatabase by inject()
    private val accounts: AccountStore by inject()
    private val apis: ApiProvider by inject()
    private val positions: Positions by inject()
    private val downloads: Downloads by inject()

    override suspend fun doWork(): Result {
        val session = accounts.current() ?: return Result.success()
        val api = apis.api(session)
        return try {
            val sent = ProgressSender(api, positions, session.deviceId, session.deviceName).flush()
            if (sent.unauthorized) return signedOut()
            if (!inputData.getBoolean(ONLY_POSITIONS, false)) {
                SyncEngine(api, RoomCatalogStore(db, session.owner)).sync()
                downloads.prune()
                downloads.fetchNext()
            }
            ContinueReadingWidget.refresh(applicationContext)
            if (sent.left > 0) Result.retry() else Result.success()
        } catch (e: CancellationException) {
            throw e
        } catch (e: KodexApiException) {
            if (e.unauthorized) signedOut() else Result.retry()
        } catch (e: IOException) {
            Result.retry()
        }
    }

    /** The key was revoked (under Inställningar on the server): back to the login. */
    private suspend fun signedOut(): Result {
        accounts.forget()
        return Result.failure()
    }

    companion object {
        const val ONLY_POSITIONS = "only_positions"
        private const val PERIODIC = "sync"
        private const val NOW = "sync-now"
        private const val POSITIONS = "positions"

        private val network = Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build()

        /** Every few hours while the app is installed (the catalog changes slowly). */
        fun schedule(context: Context) {
            val request = PeriodicWorkRequestBuilder<SyncWorker>(6, TimeUnit.HOURS).setConstraints(network).build()
            WorkManager.getInstance(context).enqueueUniquePeriodicWork(PERIODIC, ExistingPeriodicWorkPolicy.KEEP, request)
        }

        fun now(context: Context) {
            val request = OneTimeWorkRequestBuilder<SyncWorker>()
                .setConstraints(network)
                .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 30, TimeUnit.SECONDS)
                .build()
            WorkManager.getInstance(context).enqueueUniqueWork(NOW, ExistingWorkPolicy.REPLACE, request)
        }

        /** Sends the positions soon after reading (once there is a network). */
        fun sendPositions(context: Context) {
            val request = OneTimeWorkRequestBuilder<SyncWorker>()
                .setInputData(workDataOf(ONLY_POSITIONS to true))
                .setConstraints(network)
                .setInitialDelay(5, TimeUnit.SECONDS)
                .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 30, TimeUnit.SECONDS)
                .build()
            WorkManager.getInstance(context).enqueueUniqueWork(POSITIONS, ExistingWorkPolicy.REPLACE, request)
        }

        fun cancel(context: Context) {
            WorkManager.getInstance(context).apply {
                cancelUniqueWork(PERIODIC)
                cancelUniqueWork(NOW)
                cancelUniqueWork(POSITIONS)
            }
        }
    }
}
