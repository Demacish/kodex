package app.kodex.shared.reader

// The image reader's layout rules, the same as the web reader's (web/src/readers/image/layout.ts).

/** A page's [width, height] in pixels, when known. */
data class PageSize(val width: Int, val height: Int)

/** The server re-encodes pages at these widths (backend: kodex/reading/pages.py). */
val WIDTH_STEPS = listOf(480, 720, 1080, 1440, 1920, 2560, 3840)

fun widthStep(pixels: Int): Int = WIDTH_STEPS.firstOrNull { it >= pixels } ?: WIDTH_STEPS.last()

fun isWide(size: PageSize?): Boolean = size != null && size.width > size.height * 1.1

/**
 * Two-page spreads: pages in pairs, a wide page (already a spread) alone, and with
 * [coverAlone] the first page alone so the pairs line up the way the printed book does.
 * Indices are into the page list.
 */
fun spreads(count: Int, sizes: List<PageSize?>, coverAlone: Boolean): List<List<Int>> {
    val groups = mutableListOf<List<Int>>()
    var i = 0
    if (coverAlone && count > 0) {
        groups += listOf(0)
        i = 1
    }
    while (i < count) {
        if (isWide(sizes.getOrNull(i)) || i + 1 >= count || isWide(sizes.getOrNull(i + 1))) {
            groups += listOf(i)
            i += 1
        } else {
            groups += listOf(i, i + 1)
            i += 2
        }
    }
    return groups
}

fun groupOf(groups: List<List<Int>>, page: Int): Int = groups.indexOfFirst { page in it }.coerceAtLeast(0)

enum class TapAction { PREVIOUS, NEXT, MENU }

/** Where the page turns: a third at each side, a narrow edge, or nowhere (swipe only). */
enum class TapLayout(val edge: Float) { SIDES(0.3f), EDGES(0.15f), OFF(0f) }

/** What a tap at [x] (0–1 across the page) does. */
fun tapAction(x: Float, rtl: Boolean, layout: TapLayout = TapLayout.SIDES): TapAction = when {
    x < layout.edge -> if (rtl) TapAction.NEXT else TapAction.PREVIOUS
    x > 1f - layout.edge -> if (rtl) TapAction.PREVIOUS else TapAction.NEXT
    else -> TapAction.MENU
}

/** Which half of a wide page is shown on its own (a spread split for a narrow screen). */
enum class Half { LEFT, RIGHT }

/** A page, or half of one, as one step of the reader. */
data class Slot(val page: Int, val half: Half? = null)

/**
 * The reader's steps for single pages: each page alone, and a wide page as its two halves in
 * reading order (the right half first right to left) when [split].
 */
fun singlePages(count: Int, sizes: List<PageSize?>, split: Boolean, rtl: Boolean): List<List<Slot>> =
    (0 until count).flatMap { i ->
        if (split && isWide(sizes.getOrNull(i))) {
            val halves = if (rtl) listOf(Half.RIGHT, Half.LEFT) else listOf(Half.LEFT, Half.RIGHT)
            halves.map { listOf(Slot(i, it)) }
        } else {
            listOf(listOf(Slot(i)))
        }
    }

/** The step showing [page] (its first, for a split page). */
fun stepOf(steps: List<List<Slot>>, page: Int): Int = steps.indexOfFirst { step -> step.any { it.page == page } }.coerceAtLeast(0)

/**
 * A paged book's position as the server keeps it (kodex/reading/positions.py): kind "page" is
 * the 0-based page index, kind "pdf" the 1-based page number.
 */
data class PagePosition(val index: Int, val count: Int) {
    val kind: String get() = "page"
    val position: String get() = index.toString()
    val percent: Double get() = if (count <= 0) 0.0 else (index + 1) * 100.0 / count
    val finished: Boolean get() = count > 0 && index >= count - 1

    companion object {
        /** Where to open a book from what the server sent; the start for anything else. */
        fun from(kind: String?, position: String?, percent: Double, count: Int): Int {
            if (count <= 0) return 0
            val found = when (kind) {
                "page", null -> position?.toIntOrNull()
                "pdf" -> position?.toIntOrNull()?.minus(1)
                "percent" -> ((percent / 100.0) * count).toInt() - 1
                else -> null
            } ?: (if (percent > 0) ((percent / 100.0) * count).toInt() - 1 else 0)
            return found.coerceIn(0, count - 1)
        }
    }
}
