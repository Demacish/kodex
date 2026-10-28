package app.kodex.widget

import android.content.Context
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.glance.GlanceId
import androidx.glance.GlanceModifier
import androidx.glance.GlanceTheme
import androidx.glance.action.clickable
import androidx.glance.appwidget.GlanceAppWidget
import androidx.glance.appwidget.GlanceAppWidgetReceiver
import androidx.glance.appwidget.LinearProgressIndicator
import androidx.glance.appwidget.action.actionStartActivity
import androidx.glance.appwidget.cornerRadius
import androidx.glance.appwidget.provideContent
import androidx.glance.appwidget.updateAll
import androidx.glance.background
import androidx.glance.layout.Column
import androidx.glance.layout.fillMaxSize
import androidx.glance.layout.fillMaxWidth
import androidx.glance.layout.padding
import androidx.glance.text.FontWeight
import androidx.glance.text.Text
import androidx.glance.text.TextStyle
import app.kodex.MainActivity
import app.kodex.R
import app.kodex.data.db.KodexDatabase
import app.kodex.reader.ReaderActivity
import org.koin.core.context.GlobalContext

/** "Fortsätt läsa" on the home screen: the book read last, a tap from its page. */
class ContinueReadingWidget : GlanceAppWidget() {
    override suspend fun provideGlance(context: Context, id: GlanceId) {
        val db = GlobalContext.getOrNull()?.get<KodexDatabase>()
        val book = db?.catalog()?.lastRead()
        provideContent {
            GlanceTheme {
                val open = if (book != null) ReaderActivity.intent(context, book.id) else android.content.Intent(context, MainActivity::class.java)
                Column(
                    GlanceModifier.fillMaxSize().background(GlanceTheme.colors.widgetBackground).cornerRadius(16.dp).padding(12.dp)
                        .clickable(actionStartActivity(open)),
                ) {
                    Text(
                        context.getString(R.string.continue_reading),
                        style = TextStyle(color = GlanceTheme.colors.primary, fontSize = 12.sp, fontWeight = FontWeight.Medium),
                    )
                    if (book == null) {
                        Text(context.getString(R.string.widget_nothing), style = TextStyle(color = GlanceTheme.colors.onSurface))
                    } else {
                        Text(
                            book.title,
                            maxLines = 2,
                            style = TextStyle(color = GlanceTheme.colors.onSurface, fontSize = 15.sp, fontWeight = FontWeight.Bold),
                        )
                        book.seriesTitle?.let { Text(it, maxLines = 1, style = TextStyle(color = GlanceTheme.colors.onSurface, fontSize = 12.sp)) }
                        LinearProgressIndicator(
                            progress = (book.percent / 100).toFloat(),
                            modifier = GlanceModifier.fillMaxWidth().padding(top = 6.dp),
                            color = GlanceTheme.colors.primary,
                            backgroundColor = GlanceTheme.colors.surfaceVariant,
                        )
                    }
                }
            }
        }
    }

    companion object {
        suspend fun refresh(context: Context) {
            runCatching { ContinueReadingWidget().updateAll(context) }
        }
    }
}

class ContinueReadingReceiver : GlanceAppWidgetReceiver() {
    override val glanceAppWidget: GlanceAppWidget = ContinueReadingWidget()
}
