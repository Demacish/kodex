package app.kodex.shared

import app.kodex.shared.reader.Half
import app.kodex.shared.reader.PagePosition
import app.kodex.shared.reader.PageSize
import app.kodex.shared.reader.Slot
import app.kodex.shared.reader.TapAction
import app.kodex.shared.reader.TapLayout
import app.kodex.shared.reader.groupOf
import app.kodex.shared.reader.singlePages
import app.kodex.shared.reader.spreads
import app.kodex.shared.reader.stepOf
import app.kodex.shared.reader.tapAction
import app.kodex.shared.reader.widthStep
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

// The same cases as the web reader's (web/src/readers/image/layout.test.ts).
class PageLayoutTest {
    private val tall = PageSize(1000, 1500)
    private val wide = PageSize(2000, 1500)

    @Test
    fun widthsRoundUpToTheServersSteps() {
        assertEquals(480, widthStep(100))
        assertEquals(1080, widthStep(1000))
        assertEquals(3840, widthStep(9000))
    }

    @Test
    fun pagesPairUpWithWidePagesAndTheCoverAlone() {
        assertEquals(listOf(listOf(0, 1), listOf(2, 3), listOf(4)), spreads(5, List(5) { tall }, coverAlone = false))
        assertEquals(listOf(listOf(0), listOf(1, 2), listOf(3, 4)), spreads(5, List(5) { tall }, coverAlone = true))
        assertEquals(listOf(listOf(0), listOf(1), listOf(2, 3)), spreads(4, listOf(tall, wide, tall, tall), coverAlone = false))
        assertEquals(listOf(listOf(0, 1), listOf(2)), spreads(3, emptyList(), coverAlone = false))
        assertEquals(1, groupOf(spreads(5, List(5) { tall }, true), 2))
    }

    @Test
    fun tapsFollowTheReadingDirection() {
        assertEquals(TapAction.PREVIOUS, tapAction(0.1f, rtl = false))
        assertEquals(TapAction.NEXT, tapAction(0.1f, rtl = true))
        assertEquals(TapAction.MENU, tapAction(0.5f, rtl = false))
        assertEquals(TapAction.NEXT, tapAction(0.9f, rtl = false))
        assertEquals(TapAction.MENU, tapAction(0.2f, rtl = false, TapLayout.EDGES))
        assertEquals(TapAction.PREVIOUS, tapAction(0.1f, rtl = false, TapLayout.EDGES))
        assertEquals(TapAction.MENU, tapAction(0.01f, rtl = false, TapLayout.OFF))
    }

    @Test
    fun aWidePageSplitsIntoItsHalvesInReadingOrder() {
        val sizes = listOf(tall, wide, tall)
        assertEquals(
            listOf(listOf(Slot(0)), listOf(Slot(1, Half.LEFT)), listOf(Slot(1, Half.RIGHT)), listOf(Slot(2))),
            singlePages(3, sizes, split = true, rtl = false),
        )
        assertEquals(listOf(Slot(1, Half.RIGHT)), singlePages(3, sizes, split = true, rtl = true)[1])
        assertEquals(3, singlePages(3, sizes, split = false, rtl = false).size)
        assertEquals(3, stepOf(singlePages(3, sizes, split = true, rtl = false), 2))
    }

    @Test
    fun positionsAreTheServersPageIndex() {
        val last = PagePosition(9, 10)
        assertEquals("9", last.position)
        assertEquals(100.0, last.percent)
        assertTrue(last.finished)
        assertEquals(4, PagePosition.from("page", "4", 50.0, 10))
        assertEquals(3, PagePosition.from("pdf", "4", 40.0, 10))
        assertEquals(4, PagePosition.from("cfi", "/6/4", 50.0, 10))
        assertEquals(9, PagePosition.from("page", "99", 0.0, 10))
        assertEquals(0, PagePosition.from(null, null, 0.0, 10))
    }
}
