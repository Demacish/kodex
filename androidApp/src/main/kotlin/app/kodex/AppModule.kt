package app.kodex

import app.kodex.account.AccountStore
import app.kodex.account.KeystoreSealer
import app.kodex.data.Positions
import app.kodex.data.SettingsStore
import app.kodex.data.db.KodexDatabase
import app.kodex.download.Downloads
import app.kodex.download.Fetcher
import app.kodex.reader.OpenBooks
import app.kodex.sync.ApiProvider
import app.kodex.sync.SyncProblems
import app.kodex.ui.library.BookViewModel
import app.kodex.ui.library.LibraryViewModel
import app.kodex.ui.login.LoginViewModel
import app.kodex.ui.AppViewModel
import io.ktor.client.HttpClient
import io.ktor.client.engine.HttpClientEngine
import io.ktor.client.engine.okhttp.OkHttp
import io.ktor.client.plugins.HttpTimeout
import org.koin.android.ext.koin.androidContext
import org.koin.core.module.dsl.viewModel
import org.koin.dsl.module

val appModule = module {
    single<HttpClientEngine> { OkHttp.create() }
    single { KodexDatabase.build(androidContext()) }
    single { AccountStore(androidContext(), KeystoreSealer()) }
    single { SettingsStore(androidContext()) }
    single { ApiProvider(get()) }
    single { SyncProblems(androidContext()) }
    single { Positions(get()) { get<AccountStore>().deviceName } }
    single { Downloads(androidContext(), get(), get()) }
    single {
        // Downloads only: long reads, and no JSON.
        Fetcher(
            HttpClient(get<HttpClientEngine>()) {
                install(HttpTimeout) {
                    connectTimeoutMillis = 20_000
                    socketTimeoutMillis = 120_000
                }
            },
        )
    }
    single { OpenBooks(androidContext(), get(), get(), get(), get()) }
    single { AppScope() }

    viewModel { AppViewModel(androidContext(), get(), get(), get(), get(), get(), get()) }
    viewModel { LoginViewModel(androidContext(), get(), get(), get(), get()) }
    viewModel { LibraryViewModel(get()) }
    viewModel { params -> BookViewModel(params.get(), get(), get(), get()) }
}

/** Work that outlives a screen (saving the last reading position when a reader closes). */
class AppScope : kotlinx.coroutines.CoroutineScope by kotlinx.coroutines.CoroutineScope(
    kotlinx.coroutines.SupervisorJob() + kotlinx.coroutines.Dispatchers.Main.immediate,
)
