package app.kodex.ui.theme

import android.os.Build
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.ColorScheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.dynamicDarkColorScheme
import androidx.compose.material3.dynamicLightColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import app.kodex.data.ThemeChoice

// The web client's ink-and-paper palette (web/src/styles), with the device's own colours
// (Material You) on Android 12 and later.
private val light = lightColorScheme(
    primary = Color(0xFF1F3A5F),
    onPrimary = Color(0xFFFFFFFF),
    primaryContainer = Color(0xFFD5E3F7),
    onPrimaryContainer = Color(0xFF0B1D33),
    secondary = Color(0xFF8A5A2B),
    background = Color(0xFFFBF8F3),
    surface = Color(0xFFFBF8F3),
    surfaceVariant = Color(0xFFEDE6DA),
)

private val dark = darkColorScheme(
    primary = Color(0xFFA9C7EE),
    onPrimary = Color(0xFF0B1D33),
    primaryContainer = Color(0xFF2B4A72),
    onPrimaryContainer = Color(0xFFD5E3F7),
    secondary = Color(0xFFE0B98C),
    background = Color(0xFF141312),
    surface = Color(0xFF141312),
    surfaceVariant = Color(0xFF2A2724),
)

@Composable
fun KodexTheme(choice: ThemeChoice = ThemeChoice.SYSTEM, content: @Composable () -> Unit) {
    val darkTheme = when (choice) {
        ThemeChoice.SYSTEM -> isSystemInDarkTheme()
        ThemeChoice.LIGHT -> false
        ThemeChoice.DARK -> true
    }
    val context = LocalContext.current
    val colors: ColorScheme = when {
        Build.VERSION.SDK_INT >= Build.VERSION_CODES.S -> if (darkTheme) dynamicDarkColorScheme(context) else dynamicLightColorScheme(context)
        darkTheme -> dark
        else -> light
    }
    MaterialTheme(colorScheme = colors, content = content)
}
