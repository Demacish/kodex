package app.kodex.shared

import app.kodex.shared.api.Account
import app.kodex.shared.api.AppKey
import app.kodex.shared.api.AppLoginIn
import app.kodex.shared.api.AppLoginOut
import app.kodex.shared.api.AppSecondStepIn
import app.kodex.shared.api.AppTokenIn
import app.kodex.shared.api.AuthConfig
import app.kodex.shared.api.Book
import app.kodex.shared.api.Bookmark
import app.kodex.shared.api.BookmarkIn
import app.kodex.shared.api.BookMetadata
import app.kodex.shared.api.FileDigest
import app.kodex.shared.api.Library
import app.kodex.shared.api.PageDimensions
import app.kodex.shared.api.ReadingProgress
import app.kodex.shared.api.ReadingProgressIn
import app.kodex.shared.api.Recommendation
import app.kodex.shared.api.ReleaseEvent
import app.kodex.shared.api.SecondStep
import app.kodex.shared.api.Series
import app.kodex.shared.api.SyncChanges
import app.kodex.shared.api.SyncCollection
import app.kodex.shared.api.SyncDeleted
import app.kodex.shared.api.SwipeIn
import java.io.File
import kotlin.test.Test
import kotlin.test.assertTrue
import kotlinx.serialization.ExperimentalSerializationApi
import kotlinx.serialization.KSerializer
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonNamingStrategy
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive

/**
 * The hand-written client against the server's OpenAPI document (web/openapi.json, which the
 * backend's CI keeps in step with the code): every endpoint the app calls exists, every field
 * the app reads is one the server sends, and every field the server needs is one the app sends
 * (ADR 0011).
 */
@OptIn(ExperimentalSerializationApi::class)
class ContractTest {
    private val document: JsonObject by lazy {
        val path = System.getProperty("kodex.openapi") ?: error("kodex.openapi isn't set (run through Gradle)")
        Json.parseToJsonElement(File(path).readText()).jsonObject
    }
    private val schemas: JsonObject get() = document.getValue("components").jsonObject.getValue("schemas").jsonObject

    @Test
    fun theEndpointsTheAppCallsExist() {
        val paths = document.getValue("paths").jsonObject
        val called = listOf(
            "get /api/auth/config", "get /api/auth/me",
            "post /api/auth/app/login", "post /api/auth/app/second-step", "post /api/auth/app/token",
            "post /api/auth/app/logout", "get /api/sync/changes",
            "get /api/books/{book_id}/digest", "get /api/books/{book_id}/file", "get /api/books/{book_id}/cover",
            "get /api/books/{book_id}/pages/{page_index}", "get /api/books/{book_id}/pages/dimensions",
            "get /api/books/{book_id}/progress", "put /api/books/{book_id}/progress",
            "get /api/bookmarks", "put /api/bookmarks/{bookmark_id}", "delete /api/bookmarks/{bookmark_id}",
            "post /api/series/{series_id}/follow", "post /api/series/{series_id}/unfollow",
            "get /api/releases", "post /api/releases/{event_id}/dismiss",
            "get /api/ai/recommendations", "post /api/ai/recommendations/generate",
            "post /api/ai/recommendations/{recommendation_id}/swipe",
        )
        val missing = called.filter { endpoint ->
            val (method, path) = endpoint.split(" ")
            paths[path]?.jsonObject?.containsKey(method) != true
        }
        assertTrue(missing.isEmpty(), "Not in the OpenAPI document: $missing")
        val sync = paths.getValue("/api/sync/changes").jsonObject.getValue("get").jsonObject
        val parameters = sync.getValue("parameters").jsonArray.map { it.jsonObject.getValue("name").jsonPrimitive.content }
        assertTrue(parameters.containsAll(listOf("since", "progress_since", "limit")), "sync parameters: $parameters")
    }

    @Test
    fun whatTheAppReadsIsWhatTheServerSends() {
        val read: List<Pair<KSerializer<*>, String>> = listOf(
            AuthConfig.serializer() to "AuthConfig", Account.serializer() to "AccountOut",
            SecondStep.serializer() to "SecondStepOut", AppKey.serializer() to "AppKeyOut",
            AppLoginOut.serializer() to "AppLoginOut", Library.serializer() to "LibraryOut",
            Series.serializer() to "SeriesOut", BookMetadata.serializer() to "BookMetadataOut",
            Book.serializer() to "BookOut", ReadingProgress.serializer() to "ReadingProgressOut",
            SyncCollection.serializer() to "SyncCollectionOut", SyncDeleted.serializer() to "SyncDeletedOut",
            SyncChanges.serializer() to "SyncChangesOut", FileDigest.serializer() to "FileDigestOut",
            PageDimensions.serializer() to "PageDimensionsOut", Bookmark.serializer() to "BookmarkOut",
            ReleaseEvent.serializer() to "ReleaseEventOut", Recommendation.serializer() to "AIRecommendationOut",
        )
        val problems = read.flatMap { (serializer, name) -> readProblems(serializer, name) }
        assertTrue(problems.isEmpty(), problems.joinToString("\n"))
    }

    @Test
    fun whatTheServerNeedsIsWhatTheAppSends() {
        val sent: List<Pair<KSerializer<*>, String>> = listOf(
            AppLoginIn.serializer() to "AppLoginIn", AppSecondStepIn.serializer() to "AppSecondStepIn",
            AppTokenIn.serializer() to "AppTokenIn", ReadingProgressIn.serializer() to "ReadingProgressIn",
            BookmarkIn.serializer() to "BookmarkIn", SwipeIn.serializer() to "AISwipeIn",
        )
        val problems = sent.flatMap { (serializer, name) ->
            val schema = schema(name)
            val fields = fields(serializer)
            val properties = schema.getValue("properties").jsonObject.keys
            val required = schema["required"]?.jsonArray?.map { it.jsonPrimitive.content }.orEmpty()
            fields.keys.filterNot { it in properties }.map { "$name: the app sends $it, which the server doesn't take" } +
                required.filterNot { it in fields }.map { "$name: the server needs $it, which the app doesn't send" }
        }
        assertTrue(problems.isEmpty(), problems.joinToString("\n"))
    }

    private fun readProblems(serializer: KSerializer<*>, name: String): List<String> {
        val schema = schema(name)
        val properties = schema.getValue("properties").jsonObject
        val required = schema["required"]?.jsonArray?.map { it.jsonPrimitive.content }.orEmpty().toSet()
        return fields(serializer).flatMap { (field, element) ->
            val property = properties[field]?.jsonObject
                ?: return@flatMap listOf("$name: the app reads $field, which the server doesn't send")
            buildList {
                if (!element.optional && field !in required) add("$name: $field may be left out, but the app needs it")
                if (!element.optional && !element.nullable && nullable(property)) {
                    add("$name: $field may be null, but the app can't take null")
                }
            }
        }
    }

    private data class Element(val optional: Boolean, val nullable: Boolean)

    private fun fields(serializer: KSerializer<*>): Map<String, Element> {
        val descriptor = serializer.descriptor
        return (0 until descriptor.elementsCount).associate { index ->
            val name = JsonNamingStrategy.SnakeCase.serialNameForJson(descriptor, index, descriptor.getElementName(index))
            name to Element(descriptor.isElementOptional(index), descriptor.getElementDescriptor(index).isNullable)
        }
    }

    private fun schema(name: String): JsonObject = schemas[name]?.jsonObject ?: error("No schema $name")

    private fun nullable(property: JsonObject): Boolean {
        val options = property["anyOf"] as? JsonArray ?: return property["type"] == JsonPrimitive("null")
        return options.any { it.jsonObject["type"] == JsonPrimitive("null") }
    }
}
