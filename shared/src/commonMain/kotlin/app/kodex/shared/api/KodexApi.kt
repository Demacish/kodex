package app.kodex.shared.api

import io.ktor.client.HttpClient
import io.ktor.client.HttpClientConfig
import io.ktor.client.call.body
import io.ktor.client.engine.HttpClientEngine
import io.ktor.client.plugins.ResponseException
import io.ktor.client.plugins.HttpTimeout
import io.ktor.client.plugins.contentnegotiation.ContentNegotiation
import io.ktor.client.plugins.defaultRequest
import io.ktor.client.request.HttpRequestBuilder
import io.ktor.client.request.bearerAuth
import io.ktor.client.request.delete
import io.ktor.client.request.get
import io.ktor.client.request.parameter
import io.ktor.client.request.post
import io.ktor.client.request.put
import io.ktor.client.request.setBody
import io.ktor.client.statement.HttpResponse
import io.ktor.http.ContentType
import io.ktor.http.contentType
import io.ktor.http.encodeURLParameter
import io.ktor.serialization.kotlinx.json.json

/** The server said no: [status] and the `detail` it gave, when there was one. */
class KodexApiException(val status: Int, message: String) : Exception(message) {
    val unauthorized: Boolean get() = status == 401
}

/**
 * The Kodex API as the app uses it (ADR 0011: written by hand, held to web/openapi.json by
 * ContractTest). [server] is the address the user typed, such as `https://kodex.example`;
 * [key] the app's bearer token, once it has one.
 */
class KodexApi(
    server: String,
    private val key: () -> String?,
    engine: HttpClientEngine,
    configure: HttpClientConfig<*>.() -> Unit = {},
) {
    val server: String = server.trim().trimEnd('/')

    private val http = HttpClient(engine) {
        expectSuccess = true
        install(ContentNegotiation) { json(KodexJson) }
        install(HttpTimeout) {
            connectTimeoutMillis = 15_000
            socketTimeoutMillis = 60_000
        }
        defaultRequest { url("${this@KodexApi.server}/api/") }
        configure()
    }

    private fun HttpRequestBuilder.auth() {
        key()?.let { bearerAuth(it) }
    }

    private suspend inline fun <T> call(block: () -> T): T =
        try {
            block()
        } catch (e: ResponseException) {
            throw KodexApiException(e.response.status.value, detail(e.response))
        }

    private suspend fun detail(response: HttpResponse): String =
        runCatching { response.body<ErrorBody>().detail }.getOrNull() ?: response.status.description

    suspend fun config(): AuthConfig = call { http.get("auth/config").body() }

    suspend fun login(username: String, password: String, deviceName: String): AppLoginOut = call {
        http.post("auth/app/login") {
            contentType(ContentType.Application.Json)
            setBody(AppLoginIn(username, password, deviceName))
        }.body()
    }

    suspend fun secondStep(ticket: String, code: String): AppKey = call {
        http.post("auth/app/second-step") {
            contentType(ContentType.Application.Json)
            setBody(AppSecondStepIn(ticket, code))
        }.body()
    }

    /** The web page that approves this app (logging in with a passkey or the identity provider). */
    fun approveUrl(deviceName: String, challenge: String, state: String): String =
        "$server/app-login?device=${deviceName.encodeURLParameter()}&challenge=$challenge&state=$state"

    suspend fun token(code: String, verifier: String): AppKey = call {
        http.post("auth/app/token") {
            contentType(ContentType.Application.Json)
            setBody(AppTokenIn(code, verifier))
        }.body()
    }

    /** Revokes this app's key; a key that is already gone is fine. */
    suspend fun logout() {
        try {
            call { http.post("auth/app/logout") { auth() } }
        } catch (e: KodexApiException) {
            if (!e.unauthorized) throw e
        }
    }

    suspend fun me(): Account = call { http.get("auth/me") { auth() }.body() }

    suspend fun changes(since: Long, progressSince: Long, limit: Int = 500): SyncChanges = call {
        http.get("sync/changes") {
            auth()
            parameter("since", since)
            parameter("progress_since", progressSince)
            parameter("limit", limit)
        }.body()
    }

    suspend fun digest(bookId: Int): FileDigest = call { http.get("books/$bookId/digest") { auth() }.body() }

    suspend fun saveProgress(bookId: Int, progress: ReadingProgressIn): ReadingProgress = call {
        http.put("books/$bookId/progress") {
            auth()
            contentType(ContentType.Application.Json)
            setBody(progress)
        }.body()
    }

    suspend fun pageDimensions(bookId: Int): PageDimensions =
        call { http.get("books/$bookId/pages/dimensions") { auth() }.body() }

    /** All of the user's bookmarks, in reading order within each book. */
    suspend fun bookmarks(): List<Bookmark> = call { http.get("bookmarks") { auth() }.body() }

    suspend fun saveBookmark(id: String, bookmark: BookmarkIn): Bookmark = call {
        http.put("bookmarks/$id") {
            auth()
            contentType(ContentType.Application.Json)
            setBody(bookmark)
        }.body()
    }

    /** Removes a bookmark; one that is already gone is fine. */
    suspend fun deleteBookmark(id: String) {
        call { http.delete("bookmarks/$id") { auth() } }
    }

    suspend fun follow(seriesId: Int, following: Boolean): Series =
        call { http.post("series/$seriesId/${if (following) "follow" else "unfollow"}") { auth() }.body() }

    /** New numbers in the followed series, soonest first (the hidden ones left out). */
    suspend fun releases(): List<ReleaseEvent> = call { http.get("releases") { auth() }.body() }

    suspend fun dismissRelease(eventId: Int) {
        call { http.post("releases/$eventId/dismiss") { auth() } }
    }

    suspend fun recommendations(): List<Recommendation> = call { http.get("ai/recommendations") { auth() }.body() }

    /** A new batch from the server's AI; a 400 when it has none configured. */
    suspend fun generateRecommendations(): List<Recommendation> =
        call { http.post("ai/recommendations/generate") { auth() }.body() }

    /** Wanting one makes a request on the server; not wanting it hides it. */
    suspend fun swipe(recommendationId: Int, want: Boolean) {
        call {
            http.post("ai/recommendations/$recommendationId/swipe") {
                auth()
                contentType(ContentType.Application.Json)
                setBody(SwipeIn(if (want) "right" else "left"))
            }
        }
    }

    // Addresses the app downloads from itself (with the same bearer token).

    fun fileUrl(bookId: Int): String = "$server/api/books/$bookId/file"

    fun coverUrl(bookId: Int, size: String = "medium"): String = "$server/api/books/$bookId/cover?size=$size"

    fun pageUrl(bookId: Int, index: Int, maxWidth: Int? = null, trim: Boolean = false): String {
        val query = listOfNotNull(maxWidth?.let { "max_width=$it" }, "trim=true".takeIf { trim })
        return "$server/api/books/$bookId/pages/$index" + if (query.isEmpty()) "" else query.joinToString("&", prefix = "?")
    }

    fun close() = http.close()
}

@kotlinx.serialization.Serializable
private data class ErrorBody(val detail: String? = null)
