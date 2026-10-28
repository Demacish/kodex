package app.kodex.shared.api

import kotlinx.serialization.ExperimentalSerializationApi
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonNamingStrategy

/** The server's JSON: snake_case names, and fields this app doesn't know yet are skipped. */
@OptIn(ExperimentalSerializationApi::class)
val KodexJson: Json = Json {
    namingStrategy = JsonNamingStrategy.SnakeCase
    ignoreUnknownKeys = true
    explicitNulls = false
    coerceInputValues = true
}
