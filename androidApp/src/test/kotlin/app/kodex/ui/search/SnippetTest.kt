package app.kodex.ui.search

import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.font.FontWeight
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/** The server's full-text snippets (escaped HTML with the hits in `<mark>`) and where a hit opens. */
class SnippetTest {
    private val mark = SpanStyle(fontWeight = FontWeight.Bold)

    @Test
    fun theHitsAreMarkedAndTheRestUnescaped() {
        val text = snippet("Kaptenen &amp; <mark>Kiroshi</mark> såg &quot;<mark>ljuset</mark>&quot; &lt;här&gt;", mark)
        assertEquals("Kaptenen & Kiroshi såg \"ljuset\" <här>", text.text)
        val marked = text.spanStyles.map { text.text.substring(it.start, it.end) }
        assertEquals(listOf("Kiroshi", "ljuset"), marked)
    }

    @Test
    fun anUnclosedMarkKeepsItsText() {
        assertEquals("före efter", snippet("före <mark>efter", mark).text)
        assertEquals("", snippet("", mark).text)
    }

    @Test
    fun aHitOpensAnEpubAtItsChapterAndAPdfAtItsPage() {
        assertEquals("readium:OEBPS/kap7.xhtml@0.00000" to "other", textPosition("EPUB", "OEBPS/kap7.xhtml"))
        assertEquals("12" to "pdf", textPosition("pdf", "12"))
        assertNull(textPosition("cbz", "3"))
        assertNull(textPosition(null, "3"))
    }

    @Test
    fun titlesMarkTheQueryIgnoringCase() {
        val text = marked("Kiroshi och kiroshi", "KIROSHI", mark)
        assertEquals(2, text.spanStyles.size)
        assertEquals("Kiroshi och kiroshi", text.text)
    }
}
