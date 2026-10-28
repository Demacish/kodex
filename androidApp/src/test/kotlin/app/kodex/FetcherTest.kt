package app.kodex

import app.kodex.download.Fetcher
import app.kodex.download.VerificationFailed
import app.kodex.shared.api.FileDigest
import io.ktor.client.HttpClient
import io.ktor.client.engine.mock.MockEngine
import io.ktor.client.engine.mock.respond
import io.ktor.http.HttpHeaders
import io.ktor.http.HttpStatusCode
import io.ktor.http.headersOf
import java.io.File
import java.nio.file.Files
import java.security.MessageDigest
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/** Downloads resume where they stopped and only become the book when they are the server's file. */
class FetcherTest {
    private val data = ByteArray(300_000) { (it * 31 % 251).toByte() }
    private val digest = FileDigest(MessageDigest.getInstance("SHA-256").digest(data).joinToString("") { "%02x".format(it) }, data.size.toLong())
    private val ranges = mutableListOf<String?>()
    private val dir: File = Files.createTempDirectory("kodex-fetch").toFile()

    private fun server(honourRange: Boolean = true, body: ByteArray = data) = Fetcher(
        HttpClient(
            MockEngine { request ->
                val range = request.headers[HttpHeaders.Range]
                ranges += range
                assertEquals("Bearer kdx_test", request.headers[HttpHeaders.Authorization])
                val from = range?.removePrefix("bytes=")?.removeSuffix("-")?.toInt()
                if (from != null && honourRange) {
                    respond(body.copyOfRange(from, body.size), HttpStatusCode.PartialContent)
                } else {
                    respond(body, HttpStatusCode.OK, headersOf(HttpHeaders.ContentType, "application/zip"))
                }
            },
        ),
    )

    @Test
    fun aStoppedDownloadGoesOnFromWhereItWas() = runTest {
        val target = File(dir, "book.cbz")
        File(target.path + ".part").writeBytes(data.copyOfRange(0, 120_000))
        server().file("https://kodex.test/api/books/1/file", "kdx_test", target, digest) {}
        assertEquals(listOf<String?>("bytes=120000-"), ranges)
        assertArrayEquals(data, target.readBytes())
        assertFalse(File(target.path + ".part").exists())
    }

    @Test
    fun aServerThatIgnoresTheRangeSendsItAll() = runTest {
        val target = File(dir, "book.cbz")
        File(target.path + ".part").writeBytes(data.copyOfRange(0, 1000))
        server(honourRange = false).file("https://kodex.test/api/books/1/file", "kdx_test", target, digest) {}
        assertArrayEquals(data, target.readBytes())
    }

    @Test
    fun aFileThatIsntTheServersIsThrownAway() = runTest {
        val target = File(dir, "book.cbz")
        val wrong = data.copyOf().also { it[5000] = (it[5000] + 1).toByte() }
        val failed = runCatching { server(body = wrong).file("https://kodex.test/api/books/1/file", "kdx_test", target, digest) {} }
        assertTrue(failed.exceptionOrNull() is VerificationFailed)
        assertFalse(target.exists())
        assertFalse(File(target.path + ".part").exists())
    }

    @Test
    fun aCompletePartIsOnlyVerified() = runTest {
        val target = File(dir, "book.cbz")
        File(target.path + ".part").writeBytes(data)
        server().file("https://kodex.test/api/books/1/file", "kdx_test", target, digest) {}
        assertTrue(ranges.isEmpty())
        assertArrayEquals(data, target.readBytes())
    }

    @Test
    fun pagesAreFetchedOnceEach() = runTest {
        val pages = File(dir, "pages")
        val fetcher = Fetcher(
            HttpClient(
                MockEngine { request ->
                    ranges += request.url.encodedPath
                    respond(byteArrayOf(1, 2, 3), HttpStatusCode.OK, headersOf(HttpHeaders.ContentType, "image/webp"))
                },
            ),
        )
        assertEquals(3L, fetcher.page("https://kodex.test/api/books/1/pages/0", "kdx_test", pages, 0))
        assertEquals(3L, fetcher.page("https://kodex.test/api/books/1/pages/0", "kdx_test", pages, 0))
        assertEquals(1, ranges.size)
        assertEquals(listOf("0000.webp"), pages.list()?.toList())
    }
}
