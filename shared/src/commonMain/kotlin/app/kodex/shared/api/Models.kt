package app.kodex.shared.api

import kotlinx.serialization.Serializable

// The server's schemas the app uses (web/openapi.json; checked by ContractTest). Field names
// are the server's in snake_case (KodexJson's naming strategy). Enums stay strings, so a value
// a newer server adds doesn't break an older app.

@Serializable
data class AuthConfig(
    val localLogin: Boolean,
    val passkeys: Boolean,
    val oidc: Boolean,
    val oidcName: String,
    val setupRequired: Boolean,
    val authDisabled: Boolean,
)

@Serializable
data class Account(
    val id: Int,
    val username: String,
    val email: String? = null,
    val role: String,
    val isAdmin: Boolean,
    val hasPassword: Boolean,
    val oidc: Boolean,
    val twoFactor: Boolean,
    val passkeys: Int,
    val recoveryCodesLeft: Int,
    val authMethod: String,
)

@Serializable
data class AppLoginIn(val username: String, val password: String, val deviceName: String)

@Serializable
data class SecondStep(val ticket: String, val methods: List<String>)

@Serializable
data class AppKey(val id: Int, val name: String, val key: String)

@Serializable
data class AppLoginOut(val key: AppKey? = null, val secondStep: SecondStep? = null)

@Serializable
data class AppSecondStepIn(val ticket: String, val code: String)

@Serializable
data class AppTokenIn(val code: String, val verifier: String)

@Serializable
data class Library(
    val id: Int,
    val name: String,
    val path: String,
    val libraryType: String,
    val lastScannedAt: String? = null,
)

@Serializable
data class Series(
    val id: Int,
    val libraryId: Int,
    val title: String,
    val path: String,
    val startYear: Int? = null,
    val publisher: String? = null,
    val status: String? = null,
    val summary: String? = null,
    val bookCount: Int = 0,
    val isFollowing: Boolean = false,
)

@Serializable
data class BookMetadata(
    val title: String,
    val sortTitle: String,
    val authors: List<String> = emptyList(),
    val genres: List<String> = emptyList(),
    val summary: String? = null,
    val publisher: String? = null,
    val publishedYear: Int? = null,
    val language: String? = null,
)

@Serializable
data class Book(
    val id: Int,
    val libraryId: Int,
    val seriesId: Int? = null,
    val filePath: String,
    val fileFormat: String,
    val fileSize: Long,
    val pageCount: Int? = null,
    val number: Double? = null,
    val editionType: String,
    val bookMetadata: BookMetadata? = null,
) {
    val title: String get() = bookMetadata?.title ?: filePath.substringAfterLast('/').substringBeforeLast('.')
}

@Serializable
data class ReadingProgress(
    val bookId: Int,
    val position: String? = null,
    val locatorKind: String? = null,
    val progressPercent: Double,
    val isFinished: Boolean,
    val chapter: String? = null,
    val lastReadAt: String,
    val deviceId: String? = null,
    val deviceName: String? = null,
)

@Serializable
data class ReadingProgressIn(
    val position: String?,
    val locatorKind: String?,
    val progressPercent: Double,
    val isFinished: Boolean,
    val chapter: String? = null,
    val deviceId: String,
    val deviceName: String,
    val clientSeq: Long,
    val clientAt: String,
)

@Serializable
data class SyncCollection(val id: Int, val name: String, val collectionType: String, val bookIds: List<Int>)

@Serializable
data class SyncDeleted(
    val libraries: List<Int> = emptyList(),
    val series: List<Int> = emptyList(),
    val books: List<Int> = emptyList(),
    val collections: List<Int> = emptyList(),
)

@Serializable
data class SyncChanges(
    val cursor: Long,
    val more: Boolean,
    val reset: Boolean = false,
    val libraries: List<Library> = emptyList(),
    val series: List<Series> = emptyList(),
    val books: List<Book> = emptyList(),
    val collections: List<SyncCollection> = emptyList(),
    val deleted: SyncDeleted = SyncDeleted(),
    val progressCursor: Long,
    val progressMore: Boolean = false,
    val progress: List<ReadingProgress> = emptyList(),
)

@Serializable
data class FileDigest(val sha256: String, val size: Long)

/** Each page's [width, height] (null for one that couldn't be read); null while not measured. */
@Serializable
data class PageDimensions(val dimensions: List<List<Int>?>? = null, val pending: Boolean = false) {
    val sizes: List<app.kodex.shared.reader.PageSize?>?
        get() = dimensions?.map { it?.takeIf { size -> size.size == 2 }?.let { (w, h) -> app.kodex.shared.reader.PageSize(w, h) } }
}
