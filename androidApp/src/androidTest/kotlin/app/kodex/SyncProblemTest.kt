package app.kodex

import androidx.compose.ui.test.hasTestTag
import androidx.compose.ui.test.junit4.createEmptyComposeRule
import androidx.test.core.app.ActivityScenario
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.work.ListenableWorker
import androidx.work.testing.TestListenableWorkerBuilder
import app.kodex.account.AccountStore
import app.kodex.data.db.KodexDatabase
import app.kodex.download.Downloads
import app.kodex.sync.SyncProblem
import app.kodex.sync.SyncProblems
import app.kodex.sync.SyncWorker
import app.kodex.ui.wipe
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import mockwebserver3.Dispatcher
import mockwebserver3.MockResponse
import mockwebserver3.MockWebServer
import mockwebserver3.RecordedRequest
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Before
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.koin.core.context.GlobalContext

/** A sync the server answers with an error says so in the app, until one gets through. */
@RunWith(AndroidJUnit4::class)
class SyncProblemTest {
    @get:Rule val compose = createEmptyComposeRule()

    private val context = ApplicationProvider.getApplicationContext<android.content.Context>()
    private val koin get() = GlobalContext.get()
    private val db: KodexDatabase get() = koin.get()
    private val problems: SyncProblems get() = koin.get()
    private val server = MockWebServer()

    @Volatile private var broken = true

    @Before
    fun serve() = runBlocking {
        server.dispatcher = object : Dispatcher() {
            override fun dispatch(request: RecordedRequest): MockResponse = when {
                request.url.encodedPath != "/api/sync/changes" -> MockResponse.Builder().code(404).body("""{"detail":"Not found"}""").build()
                broken -> MockResponse.Builder().code(500).body("Internal Server Error").build()
                else -> MockResponse.Builder().code(200).setHeader("Content-Type", "application/json")
                    .body("""{"cursor":0,"more":false,"progress_cursor":0}""").build()
            }
        }
        server.start()
        wipe(db, koin.get<Downloads>())
        problems.clear()
        koin.get<AccountStore>().save(server.url("/").toString().trimEnd('/'), "kdx_test", "anna")
    }

    @After
    fun stop() = runBlocking {
        runCatching { server.close() }
        wipe(db, koin.get<Downloads>())
        problems.clear()
        koin.get<AccountStore>().forget()
    }

    private fun sync() = runBlocking { TestListenableWorkerBuilder<SyncWorker>(context).build().doWork() }

    @Test
    fun aFailedSyncSaysWhyUntilOneGetsThrough() = runBlocking {
        assertEquals(ListenableWorker.Result.retry(), sync())
        assertEquals(500, (problems.problem.first() as SyncProblem.Server).status)

        // Nothing has come yet, so the empty home says why, with a way to try again.
        ActivityScenario.launch(MainActivity::class.java).use {
            compose.waitUntil(timeoutMillis = 15_000) { compose.onAllNodes(hasTestTag("sync-problem")).fetchSemanticsNodes().isNotEmpty() }
        }

        broken = false
        assertEquals(ListenableWorker.Result.success(), sync())
        assertNull(problems.problem.first())
    }
}
