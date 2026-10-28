package app.kodex.reader.epub

import android.app.Application
import android.content.Context
import app.kodex.data.Position
import app.kodex.data.db.ProgressEntity
import org.readium.navigator.media.tts.AndroidTtsNavigatorFactory
import org.readium.navigator.media.tts.TtsNavigatorFactory
import org.readium.r2.navigator.epub.EpubNavigatorFactory
import org.readium.r2.shared.ExperimentalReadiumApi
import org.readium.r2.shared.publication.Locator
import org.readium.r2.shared.publication.Publication
import org.readium.r2.shared.publication.services.locateProgression
import org.readium.r2.shared.util.Url
import org.readium.r2.shared.util.asset.AssetRetriever
import org.readium.r2.shared.util.getOrElse
import org.readium.r2.shared.util.http.DefaultHttpClient
import org.readium.r2.streamer.PublicationOpener
import org.readium.r2.streamer.parser.DefaultPublicationParser
import java.io.File

/**
 * An EPUB opened with Readium, and where to start in it. Positions go to the server as kind
 * "other" in a compact form of Readium's locator ([encode]); a position another reader saved
 * (a CFI, a KOReader xpointer) opens at its percentage.
 */
@OptIn(ExperimentalReadiumApi::class)
class EpubSession private constructor(
    val bookId: Int,
    val publication: Publication,
    val initialLocator: Locator?,
) {
    val navigatorFactory = EpubNavigatorFactory(publication)

    /** Reading aloud, when the device has a text-to-speech engine and the book has text. */
    fun ttsFactory(context: Context): AndroidTtsNavigatorFactory? =
        TtsNavigatorFactory(context.applicationContext as Application, publication)

    fun close() = publication.close()

    companion object {
        private const val PREFIX = "readium:"

        suspend fun open(context: Context, bookId: Int, file: File, progress: ProgressEntity?): EpubSession {
            val http = DefaultHttpClient()
            val assets = AssetRetriever(context.contentResolver, http)
            val opener = PublicationOpener(DefaultPublicationParser(context, http, assets, pdfFactory = null))
            val asset = assets.retrieve(file).getOrElse { throw IllegalStateException(it.message) }
            val publication = opener.open(asset, allowUserInteraction = false).getOrElse {
                asset.close()
                throw IllegalStateException(it.message)
            }
            return EpubSession(bookId, publication, startAt(publication, progress))
        }

        private suspend fun startAt(publication: Publication, progress: ProgressEntity?): Locator? {
            progress ?: return null
            decode(publication, progress.locatorKind, progress.position)?.let { return it }
            return if (progress.percent > 0) publication.locateProgression(progress.percent / 100.0) else null
        }

        /** `readium:<href>@<progression>`: short enough for the server's 512 characters. */
        fun encode(locator: Locator): Position {
            val progression = locator.locations.progression ?: 0.0
            val total = locator.locations.totalProgression ?: 0.0
            return Position(
                position = "$PREFIX${locator.href}@${"%.5f".format(java.util.Locale.ROOT, progression)}".take(512),
                locatorKind = "other",
                percent = (total * 100).coerceIn(0.0, 100.0),
                finished = total >= 0.995,
                chapter = locator.title?.take(200),
            )
        }

        fun decode(publication: Publication, kind: String?, position: String?): Locator? {
            if (kind != "other" || position == null || !position.startsWith(PREFIX)) return null
            val body = position.removePrefix(PREFIX)
            val at = body.lastIndexOf('@')
            if (at <= 0) return null
            val href = Url(body.substring(0, at)) ?: return null
            val progression = body.substring(at + 1).toDoubleOrNull() ?: 0.0
            val link = publication.linkWithHref(href) ?: return null
            return publication.locatorFromLink(link)?.copyWithLocations(progression = progression)
        }
    }
}
