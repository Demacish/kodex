package app.kodex.download

import app.kodex.shared.api.FileDigest
import io.ktor.client.HttpClient
import io.ktor.client.request.bearerAuth
import io.ktor.client.request.header
import io.ktor.client.request.prepareGet
import io.ktor.client.statement.HttpResponse
import io.ktor.client.statement.bodyAsChannel
import io.ktor.http.HttpHeaders
import io.ktor.http.HttpStatusCode
import io.ktor.http.contentLength
import io.ktor.http.contentType
import io.ktor.utils.io.jvm.javaio.toInputStream
import java.io.File
import java.io.FileInputStream
import java.io.FileOutputStream
import java.io.IOException
import java.io.InputStream
import java.security.MessageDigest
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.withContext

/** The file came, but isn't the one the server has: it is thrown away, not kept. */
class VerificationFailed(message: String) : IOException(message)

/** The server answered with something other than the file (an error worth not retrying for). */
class Refused(val status: Int) : IOException("The server answered $status")

/**
 * Fetches books over HTTP. A file goes to `<name>.part` first and resumes from where it stopped
 * (Range), and becomes the book only when its size and SHA-256 are the server's (GET
 * /api/books/{id}/digest). Pages are fetched one by one and skipped when already there.
 */
class Fetcher(private val http: HttpClient) {
    suspend fun file(url: String, key: String, target: File, expected: FileDigest, onProgress: suspend (Long) -> Unit) {
        target.parentFile?.mkdirs()
        val part = File(target.path + ".part")
        if (part.length() > expected.size) part.delete()
        if (part.length() < expected.size) {
            val have = part.length()
            http.prepareGet(url) {
                bearerAuth(key)
                if (have > 0) header(HttpHeaders.Range, "bytes=$have-")
            }.execute { response ->
                when (response.status) {
                    HttpStatusCode.PartialContent -> copy(response, part, append = true, from = have, onProgress)
                    HttpStatusCode.OK -> copy(response, part, append = false, from = 0, onProgress)
                    HttpStatusCode.RequestedRangeNotSatisfiable -> part.delete()
                    else -> throw Refused(response.status.value)
                }
            }
        }
        val size = part.length()
        if (size != expected.size) {
            if (size > expected.size || size == 0L) part.delete()
            throw if (size > expected.size) VerificationFailed("$size bytes, the server has ${expected.size}") else IOException("Stopped at $size of ${expected.size} bytes")
        }
        val sha256 = sha256(part)
        if (!sha256.equals(expected.sha256, ignoreCase = true)) {
            part.delete()
            throw VerificationFailed("SHA-256 $sha256, the server has ${expected.sha256}")
        }
        target.delete()
        if (!part.renameTo(target)) throw IOException("Could not move the file into place")
    }

    /** One page into [dir] as `0001.jpg` and so on; returns its size. Already there: skipped. */
    suspend fun page(url: String, key: String, dir: File, index: Int): Long {
        dir.mkdirs()
        val name = "%04d".format(index)
        dir.listFiles { file -> file.name.startsWith("$name.") && !file.name.endsWith(".part") }?.firstOrNull()?.let { return it.length() }
        return http.prepareGet(url) { bearerAuth(key) }.execute { response ->
            if (response.status != HttpStatusCode.OK) throw Refused(response.status.value)
            val extension = when (response.contentType()?.contentSubtype) {
                "png" -> "png"
                "webp" -> "webp"
                "gif" -> "gif"
                "avif" -> "avif"
                else -> "jpg"
            }
            val part = File(dir, "$name.$extension.part")
            copy(response, part, append = false, from = 0) {}
            val expected = response.contentLength()
            if (expected != null && part.length() != expected) {
                part.delete()
                throw IOException("Page $index stopped at ${part.length()} of $expected bytes")
            }
            val done = File(dir, "$name.$extension")
            if (!part.renameTo(done)) throw IOException("Could not move page $index into place")
            done.length()
        }
    }

    private suspend fun copy(response: HttpResponse, part: File, append: Boolean, from: Long, onProgress: suspend (Long) -> Unit) {
        val input: InputStream = response.bodyAsChannel().toInputStream()
        withContext(Dispatchers.IO) {
            FileOutputStream(part, append).use { out ->
                val buffer = ByteArray(64 * 1024)
                var written = from
                var reported = 0L
                while (true) {
                    ensureActive()
                    val read = input.read(buffer)
                    if (read < 0) break
                    out.write(buffer, 0, read)
                    written += read
                    if (written - reported >= 256 * 1024) {
                        reported = written
                        onProgress(written)
                    }
                }
                onProgress(written)
            }
        }
    }

    companion object {
        fun sha256(file: File): String {
            val digest = MessageDigest.getInstance("SHA-256")
            FileInputStream(file).use { input ->
                val buffer = ByteArray(256 * 1024)
                while (true) {
                    val read = input.read(buffer)
                    if (read < 0) break
                    digest.update(buffer, 0, read)
                }
            }
            return digest.digest().joinToString("") { "%02x".format(it) }
        }
    }
}
