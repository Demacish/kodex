package app.kodex

import android.app.Application
import app.kodex.reader.image.ZipPageFetcher
import app.kodex.reader.image.ZipPageKeyer
import app.kodex.sync.SyncWorker
import coil3.ImageLoader
import coil3.PlatformContext
import coil3.SingletonImageLoader
import coil3.network.ktor3.KtorNetworkFetcherFactory
import io.ktor.client.HttpClient
import io.ktor.client.engine.HttpClientEngine
import org.koin.android.ext.android.get
import org.koin.android.ext.koin.androidContext
import org.koin.core.context.startKoin

class KodexApplication : Application(), SingletonImageLoader.Factory {
    override fun onCreate() {
        super.onCreate()
        startKoin {
            androidContext(this@KodexApplication)
            modules(appModule)
        }
        SyncWorker.schedule(this)
    }

    /** Covers and pages from the server go through the app's own HTTP engine. */
    override fun newImageLoader(context: PlatformContext): ImageLoader =
        ImageLoader.Builder(context)
            .components {
                add(KtorNetworkFetcherFactory(httpClient = { HttpClient(get<HttpClientEngine>()) }))
                add(ZipPageFetcher.Factory())
                add(ZipPageKeyer())
            }
            .build()
}
