package app.kodex.shared

import app.kodex.shared.reader.inPageOrder
import app.kodex.shared.reader.isPage
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

// The expected orders are what the server's natural_key gives (kodex/formats/archive.py): the
// device must count pages exactly as the server does.
class PageOrderTest {
    @Test
    fun onlyImagesArePages() {
        assertTrue(isPage("Kapitel 1/001.JPG"))
        assertTrue(isPage("a.webp"))
        assertFalse(isPage("ComicInfo.xml"))
        assertFalse(isPage("__MACOSX/001.jpg"))
        assertFalse(isPage("bilder/._001.jpg"))
        assertFalse(isPage(".jpg"))
        assertFalse(isPage("bilder/"))
    }

    @Test
    fun numbersSortAsNumbersFolderByFolder() {
        val names = listOf("p10.jpg", "p2.jpg", "p1.jpg", "omslag.jpg", "B/1.jpg", "a/2.jpg", "a/10.jpg", "info.txt", "P3.png")
        assertEquals(
            listOf("a/2.jpg", "a/10.jpg", "B/1.jpg", "omslag.jpg", "p1.jpg", "p2.jpg", "P3.png", "p10.jpg"),
            names.inPageOrder { it },
        )
    }

    @Test
    fun leadingZerosAndLeadingNumbers() {
        assertEquals(listOf("01.jpg", "2.jpg", "010.jpg"), listOf("010.jpg", "2.jpg", "01.jpg").inPageOrder { it })
        assertEquals(listOf("1a.jpg", "a.jpg"), listOf("a.jpg", "1a.jpg").inPageOrder { it })
    }
}
