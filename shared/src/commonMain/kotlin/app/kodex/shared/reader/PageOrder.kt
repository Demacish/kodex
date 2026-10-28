package app.kodex.shared.reader

// Which files in a comic archive are pages, and their order: the server's rules
// (backend kodex/formats/archive.py, is_page and natural_key), so that page 12 on the device is
// page 12 on the server and in every other client.

val IMAGE_EXTENSIONS = setOf(".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".avif", ".jxl")

/** An image, not a directory or a macOS resource fork (`__MACOSX/`, `._name`). */
fun isPage(name: String): Boolean {
    if (name.endsWith('/')) return false
    val parts = name.replace('\\', '/').split('/').filter { it.isNotEmpty() && it != "." }
    val file = parts.lastOrNull() ?: return false
    if (file.startsWith("._") || "__MACOSX" in parts) return false
    val dot = file.lastIndexOf('.')
    // As PurePosixPath.suffix: a leading dot alone (".jpg") isn't a suffix, nor is a trailing one.
    if (dot <= 0 || dot == file.length - 1) return false
    return file.substring(dot).lowercase() in IMAGE_EXTENSIONS
}

/** "page 2" before "page 10", folder by folder; numbers before text, as Python's tuples sort. */
val naturalOrder: Comparator<String> = Comparator { a, b ->
    val left = tokens(a)
    val right = tokens(b)
    for (i in 0 until minOf(left.size, right.size)) {
        val compared = compareTokens(left[i], right[i])
        if (compared != 0) return@Comparator compared
    }
    left.size.compareTo(right.size)
}

fun <T> List<T>.inPageOrder(name: (T) -> String): List<T> = filter { isPage(name(it)) }.sortedWith(compareBy(naturalOrder, name))

private sealed interface Token

private data class Digits(val value: String) : Token

private data class Text(val value: String) : Token

/** As `re.split(r"(\d+)", name.casefold())`: text and digit runs taking turns, text first. */
private fun tokens(name: String): List<Token> {
    val folded = name.lowercase()
    val out = mutableListOf<Token>()
    var i = 0
    var text = StringBuilder()
    while (i < folded.length) {
        if (folded[i].isDigit()) {
            out += Text(text.toString())
            text = StringBuilder()
            val start = i
            while (i < folded.length && folded[i].isDigit()) i++
            out += Digits(folded.substring(start, i).map { '0' + it.digitToInt() }.joinToString("").trimStart('0'))
        } else {
            text.append(folded[i])
            i++
        }
    }
    out += Text(text.toString())
    return out
}

private fun compareTokens(a: Token, b: Token): Int = when {
    a is Digits && b is Digits -> if (a.value.length != b.value.length) a.value.length.compareTo(b.value.length) else a.value.compareTo(b.value)
    a is Digits -> -1
    b is Digits -> 1
    else -> (a as Text).value.compareTo((b as Text).value)
}
