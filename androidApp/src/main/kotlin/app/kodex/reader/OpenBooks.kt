package app.kodex.reader

import android.content.Context
import app.kodex.account.AccountStore
import app.kodex.data.db.BookEntity
import app.kodex.data.db.DownloadKinds
import app.kodex.data.db.DownloadState
import app.kodex.data.db.KodexDatabase
import app.kodex.data.db.ProgressEntity
import app.kodex.download.Downloads
import app.kodex.reader.epub.EpubSession
import app.kodex.reader.image.ZipFiles
import app.kodex.shared.api.KodexJson
import app.kodex.shared.api.PageDimensions
import app.kodex.shared.reader.PageSize
import app.kodex.shared.reader.widthStep
import app.kodex.sync.ApiProvider
import coil3.network.NetworkHeaders
import java.io.File
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

/** The pages of an image book: Coil data for each, with their sizes when known. */
class ImagePages(val pages: List<Any>, val sizes: List<PageSize?>, val headers: NetworkHeaders?, val offline: Boolean) {
    val count: Int get() = pages.size
}

/** What the reader opens a book from. */
sealed interface Opened {
    data class Images(val pages: ImagePages) : Opened

    data class Epub(val session: EpubSession) : Opened

    data class Pdf(val file: File) : Opened

    /** An EPUB or PDF has to be downloaded first; an image book needs the network. */
    data object NeedsDownload : Opened

    data class Failed(val message: String) : Opened
}

/** Opens books for the reader, from the download when there is one, else from the server. */
class OpenBooks(
    private val context: Context,
    private val db: KodexDatabase,
    private val downloads: Downloads,
    private val accounts: AccountStore,
    private val apis: ApiProvider,
) {
    /** The open EPUB, kept while its reader is (also over a rotation, when the activity is recreated). */
    @Volatile var epub: EpubSession? = null
        private set

    /** [start] opens it somewhere else than its position (a bookmark). */
    suspend fun open(book: BookEntity, screenWidth: Int, trim: Boolean = false, start: ProgressEntity? = null): Opened = withContext(Dispatchers.IO) {
        val download = db.downloads().get(book.id)?.takeIf { it.state == DownloadState.DONE }
        val sizes = download?.pageSizes?.let { runCatching { KodexJson.decodeFromString(PageDimensions.serializer(), it).sizes }.getOrNull() }
        try {
            when {
                download != null && download.kind == DownloadKinds.PAGES -> {
                    val files = downloads.pages(book.id).listFiles { f -> !f.name.endsWith(".part") }?.sortedBy { it.name }.orEmpty()
                    Opened.Images(ImagePages(files, sizes ?: emptyList(), null, offline = true))
                }
                download != null && book.format == "cbz" -> {
                    val pages = ZipFiles.pages(downloads.file(book.id, book.format))
                    Opened.Images(ImagePages(pages, sizes ?: emptyList(), null, offline = true))
                }
                download != null && book.format == "epub" -> Opened.Epub(openEpub(book, downloads.file(book.id, "epub"), start))
                download != null && book.format == "pdf" -> Opened.Pdf(downloads.file(book.id, "pdf"))
                book.format == "epub" || book.format == "pdf" -> Opened.NeedsDownload
                else -> remotePages(book, screenWidth, trim)
            }
        } catch (e: Exception) {
            Opened.Failed(e.message ?: e.javaClass.simpleName)
        }
    }

    private suspend fun remotePages(book: BookEntity, screenWidth: Int, trim: Boolean): Opened {
        val session = accounts.current() ?: return Opened.NeedsDownload
        val api = apis.api(session)
        val dimensions = runCatching { api.pageDimensions(book.id) }.getOrElse { return Opened.NeedsDownload }
        val count = book.pageCount ?: dimensions.dimensions?.size ?: return Opened.Failed("The server hasn't counted the pages yet")
        val width = widthStep(screenWidth)
        val headers = NetworkHeaders.Builder().set("Authorization", "Bearer ${session.key}").build()
        val urls = List(count) { api.pageUrl(book.id, it, width, trim) }
        // Trimmed pages change shape, so the server's sizes no longer hold for them.
        return Opened.Images(ImagePages(urls, if (trim) emptyList() else dimensions.sizes.orEmpty(), headers, offline = false))
    }

    private suspend fun openEpub(book: BookEntity, file: File, start: ProgressEntity?): EpubSession {
        epub?.let { if (it.bookId == book.id) return it else it.close() }
        val progress = start ?: db.catalog().progressNow(book.id)
        return EpubSession.open(context, book.id, file, progress).also { epub = it }
    }

    fun close(bookId: Int) {
        epub?.takeIf { it.bookId == bookId }?.let {
            it.close()
            epub = null
        }
    }
}
