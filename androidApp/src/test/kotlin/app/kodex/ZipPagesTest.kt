package app.kodex

import app.kodex.reader.image.ZipFiles
import java.io.File
import java.nio.file.Files
import java.util.zip.ZipEntry
import java.util.zip.ZipOutputStream
import org.junit.Assert.assertEquals
import org.junit.Test

/** A downloaded CBZ has the server's pages in the server's order (shared PageOrder). */
class ZipPagesTest {
    @Test
    fun pagesComeInTheServersOrder() {
        val file = File(Files.createTempDirectory("kodex-zip").toFile(), "book.cbz")
        ZipOutputStream(file.outputStream()).use { zip ->
            listOf("p10.jpg", "p2.jpg", "ComicInfo.xml", "__MACOSX/p1.jpg", "p1.jpg", "kapitel/._p3.jpg", "Kapitel/p3.png").forEach {
                zip.putNextEntry(ZipEntry(it))
                zip.write(byteArrayOf(1))
                zip.closeEntry()
            }
        }
        assertEquals(listOf("Kapitel/p3.png", "p1.jpg", "p2.jpg", "p10.jpg"), ZipFiles.pages(file).map { it.entry })
        ZipFiles.close(file)
    }
}
