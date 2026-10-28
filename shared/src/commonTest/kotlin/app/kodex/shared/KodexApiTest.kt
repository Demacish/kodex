package app.kodex.shared

import app.kodex.shared.api.KodexApiException
import io.ktor.http.HttpHeaders
import io.ktor.http.HttpMethod
import io.ktor.http.HttpStatusCode
import io.ktor.http.content.TextContent
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertNull
import kotlin.test.assertTrue
import kotlinx.coroutines.test.runTest

class KodexApiTest {
    @Test
    fun logsInWithThePassword() = runTest {
        val server = FakeServer { request ->
            assertEquals("https://kodex.test/api/auth/app/login", request.url.toString())
            assertNull(request.headers[HttpHeaders.Authorization])
            val body = (request.body as TextContent).text
            assertEquals("""{"username":"anna","password":"hemligt","device_name":"Pixel 9"}""", body)
            json("""{"key":{"id":4,"name":"App: Pixel 9","key":"kdx_abc"},"second_step":null}""")
        }
        val answer = server.api(key = null).login("anna", "hemligt", "Pixel 9")
        assertEquals("kdx_abc", answer.key?.key)
        assertNull(answer.secondStep)
    }

    @Test
    fun theSecondStepComesBackWhenTheAccountHasOne() = runTest {
        val server = FakeServer { json("""{"key":null,"second_step":{"ticket":"t1","methods":["totp","recovery"]}}""") }
        val answer = server.api(key = null).login("anna", "hemligt", "Pixel")
        assertEquals("t1", answer.secondStep?.ticket)
        assertEquals(listOf("totp", "recovery"), answer.secondStep?.methods)
    }

    @Test
    fun theServersRefusalCarriesItsDetail() = runTest {
        val server = FakeServer { json("""{"detail":"Wrong username or password"}""", HttpStatusCode.Unauthorized) }
        val refused = assertFailsWith<KodexApiException> { server.api(key = null).login("anna", "fel", "Pixel") }
        assertEquals(401, refused.status)
        assertEquals("Wrong username or password", refused.message)
        assertTrue(refused.unauthorized)
    }

    @Test
    fun theKeyGoesWithEveryCallAndUnknownFieldsAreSkipped() = runTest {
        val server = FakeServer { request ->
            assertEquals("Bearer kdx_test", request.headers[HttpHeaders.Authorization])
            json(
                """{"id":1,"username":"anna","email":null,"role":"user","is_admin":false,"has_password":true,
                "oidc":false,"two_factor":true,"passkeys":2,"recovery_codes_left":8,"auth_method":"api_key",
                "something_new":{"a":1}}""",
            )
        }
        val me = server.api().me()
        assertEquals("anna", me.username)
        assertEquals(2, me.passkeys)
    }

    @Test
    fun changesAsksFromBothCursors() = runTest {
        val server = FakeServer { request ->
            assertEquals("/api/sync/changes", request.url.encodedPath)
            assertEquals("12", request.url.parameters["since"])
            assertEquals("7", request.url.parameters["progress_since"])
            json("""{"cursor":12,"more":false,"progress_cursor":7}""")
        }
        val changes = server.api().changes(12, 7)
        assertEquals(12, changes.cursor)
        assertTrue(changes.books.isEmpty() && changes.deleted.books.isEmpty())
    }

    @Test
    fun aPositionIsSentInTheServersNames() = runTest {
        val server = FakeServer { request ->
            assertEquals(HttpMethod.Put, request.method)
            val body = (request.body as TextContent).text
            assertTrue(""""locator_kind":"page"""" in body && """"client_seq":3""" in body, body)
            json("""{"book_id":5,"position":"9","locator_kind":"page","progress_percent":50.0,"is_finished":false,
                "dismissed_at":null,"last_read_at":"2026-10-26T10:00:00Z"}""")
        }
        val saved = server.api().saveProgress(
            5,
            app.kodex.shared.api.ReadingProgressIn("9", "page", 50.0, false, null, "dev-1", "Pixel", 3, "2026-10-26T10:00:00Z"),
        )
        assertEquals("9", saved.position)
    }

    @Test
    fun aRevokedKeyLogsOutQuietly() = runTest {
        val server = FakeServer { json("""{"detail":"Not authenticated"}""", HttpStatusCode.Unauthorized) }
        server.api().logout()
        assertEquals(1, server.requests.size)
    }

    @Test
    fun addressesAreTheServers() {
        val api = FakeServer { error("no calls") }.api()
        assertEquals("https://kodex.test/api/books/3/file", api.fileUrl(3))
        assertEquals("https://kodex.test/api/books/3/pages/0?max_width=1080", api.pageUrl(3, 0, 1080))
        assertEquals("https://kodex.test/api/books/3/pages/2?max_width=720&trim=true", api.pageUrl(3, 2, 720, trim = true))
        assertEquals("https://kodex.test/api/books/3/pages/2", api.pageUrl(3, 2))
        assertEquals(
            "https://kodex.test/app-login?device=Min%20telefon&challenge=abc&state=xyz",
            api.approveUrl("Min telefon", "abc", "xyz"),
        )
    }
}
