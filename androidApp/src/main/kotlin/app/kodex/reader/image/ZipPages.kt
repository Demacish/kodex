package app.kodex.reader.image

import app.kodex.shared.reader.inPageOrder
import coil3.ImageLoader
import coil3.decode.DataSource
import coil3.decode.ImageSource
import coil3.fetch.FetchResult
import coil3.fetch.Fetcher
import coil3.fetch.SourceFetchResult
import coil3.key.Keyer
import coil3.request.Options
import java.io.File
import java.nio.charset.Charset
import java.util.zip.ZipFile
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okio.Buffer
import okio.source

/** One page inside a downloaded CBZ, as Coil data. */
data class ZipPage(val file: File, val entry: String)

/**
 * Opens CBZ files the way the server does: names without the UTF-8 flag are CP437 (as Python's
 * zipfile reads them), so the page order, and with it every page number, is the server's.
 * The last few archives stay open while a reader turns their pages.
 */
object ZipFiles {
    private val cp437: Charset = runCatching { Charset.forName("IBM437") }.getOrDefault(Charsets.UTF_8)
    private val open = object : LinkedHashMap<String, ZipFile>(4, 0.75f, true) {
        override fun removeEldestEntry(eldest: MutableMap.MutableEntry<String, ZipFile>): Boolean =
            (size > 2).also { if (it) runCatching { eldest.value.close() } }
    }

    @Synchronized
    fun get(file: File): ZipFile = open.getOrPut(file.path) { ZipFile(file, cp437) }

    @Synchronized
    fun close(file: File) {
        open.remove(file.path)?.let { runCatching { it.close() } }
    }

    /** The archive's pages in reading order. */
    fun pages(file: File): List<ZipPage> {
        val zip = get(file)
        return zip.entries().asSequence().filterNot { it.isDirectory }.map { it.name }.toList()
            .inPageOrder { it }
            .map { ZipPage(file, it) }
    }
}

class ZipPageFetcher(private val page: ZipPage, private val options: Options) : Fetcher {
    override suspend fun fetch(): FetchResult = withContext(Dispatchers.IO) {
        val zip = ZipFiles.get(page.file)
        val entry = zip.getEntry(page.entry) ?: error("No page ${page.entry}")
        val buffer = Buffer()
        zip.getInputStream(entry).use { buffer.writeAll(it.source()) }
        SourceFetchResult(ImageSource(buffer, options.fileSystem), mimeType = null, dataSource = DataSource.DISK)
    }

    class Factory : Fetcher.Factory<ZipPage> {
        override fun create(data: ZipPage, options: Options, imageLoader: ImageLoader): Fetcher = ZipPageFetcher(data, options)
    }
}

class ZipPageKeyer : Keyer<ZipPage> {
    override fun key(data: ZipPage, options: Options): String = "zip:${data.file.path}:${data.file.lastModified()}:${data.entry}"
}
