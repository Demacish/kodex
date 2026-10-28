package app.kodex.shared

import app.kodex.shared.progress.Outbox
import app.kodex.shared.progress.Outgoing
import app.kodex.shared.progress.ProgressSender
import io.ktor.http.HttpStatusCode
import io.ktor.http.content.TextContent
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue
import kotlinx.coroutines.test.runTest

private class MemoryOutbox(vararg items: Outgoing) : Outbox {
    val items = items.toMutableList()

    override suspend fun pending() = items.toList()

    override suspend fun sent(id: Long) {
        items.removeAll { it.id == id }
    }
}

private fun outgoing(id: Long, bookId: Int, page: Int) =
    Outgoing(id, bookId, page.toString(), "page", page * 10.0, false, null, seq = id, at = "2026-10-26T10:0$id:00Z")

private const val SAVED = """{"book_id":1,"progress_percent":0.0,"is_finished":false,"last_read_at":"2026-10-26T10:00:00Z"}"""

class ProgressSenderTest {
    @Test
    fun sendsInOrderWithTheDeviceAndItsNumbers() = runTest {
        val server = FakeServer { json(SAVED) }
        val outbox = MemoryOutbox(outgoing(1, 1, 2), outgoing(2, 1, 3))
        val result = ProgressSender(server.api(), outbox, "dev-1", "Pixel").flush()
        assertEquals(2, result.sent)
        assertTrue(outbox.items.isEmpty())
        val bodies = server.requests.map { (it.body as TextContent).text }
        assertTrue(""""client_seq":1""" in bodies[0] && """"client_seq":2""" in bodies[1])
        assertTrue(bodies.all { """"device_id":"dev-1"""" in it && """"device_name":"Pixel"""" in it })
    }

    @Test
    fun withoutANetworkTheRestWaits() = runTest {
        var calls = 0
        val server = FakeServer {
            calls += 1
            if (calls == 2) throw IllegalStateException("no network") else json(SAVED)
        }
        val outbox = MemoryOutbox(outgoing(1, 1, 2), outgoing(2, 1, 3), outgoing(3, 1, 4))
        val result = ProgressSender(server.api(), outbox, "dev-1", "Pixel").flush()
        assertEquals(1, result.sent)
        assertEquals(2, result.left)
        assertEquals(listOf(2L, 3L), outbox.items.map { it.id })
    }

    @Test
    fun aBookThatIsGoneDropsItsPositions() = runTest {
        val server = FakeServer { request ->
            if ("/books/9/" in request.url.encodedPath) json("""{"detail":"Not found"}""", HttpStatusCode.NotFound) else json(SAVED)
        }
        val outbox = MemoryOutbox(outgoing(1, 9, 2), outgoing(2, 1, 3))
        val result = ProgressSender(server.api(), outbox, "dev-1", "Pixel").flush()
        assertEquals(1, result.dropped)
        assertEquals(1, result.sent)
        assertTrue(outbox.items.isEmpty())
    }

    @Test
    fun aRevokedKeyStopsEverything() = runTest {
        val server = FakeServer { json("""{"detail":"Not authenticated"}""", HttpStatusCode.Unauthorized) }
        val outbox = MemoryOutbox(outgoing(1, 1, 2), outgoing(2, 1, 3))
        val result = ProgressSender(server.api(), outbox, "dev-1", "Pixel").flush()
        assertTrue(result.unauthorized)
        assertEquals(2, outbox.items.size)
        assertEquals(1, server.requests.size)
    }
}
