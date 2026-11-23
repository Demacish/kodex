package app.kodex.ui.theme

import android.app.Activity
import android.content.Context
import android.os.Build
import androidx.annotation.RequiresApi
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.ColorScheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Shapes
import androidx.compose.material3.Typography
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.dynamicDarkColorScheme
import androidx.compose.material3.dynamicLightColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.Immutable
import androidx.compose.runtime.ReadOnlyComposable
import androidx.compose.runtime.SideEffect
import androidx.compose.runtime.remember
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.compositeOver
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalView
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.Font
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.em
import androidx.compose.ui.unit.sp
import androidx.core.view.WindowCompat
import app.kodex.R
import app.kodex.data.Accent
import app.kodex.data.ThemeChoice

/**
 * Kodex's own look (the 2.4 redesign): a deep blue-grey canvas (or cool paper in the light
 * theme) where the covers give the colour, one accent for what is active (Kodex's periwinkle
 * unless the user picks another, or the device's own), and teal only for what is on the device
 * or done. Surfaces step up in lightness instead of casting shadows, with a hairline border.
 */
@Immutable
data class KodexColors(
    val dark: Boolean,
    /** Fills: the main button, progress, the chosen tab. */
    val accent: Color,
    val onAccent: Color,
    /** Accent text and icons on the surfaces (readable on them). */
    val accentText: Color,
    /** The accent faintly over a surface: chosen chips, badges. */
    val accentSoft: Color,
    /** On the device: downloaded, offline. */
    val offline: Color,
    val offlineText: Color,
    val offlineSoft: Color,
    val background: Color,
    /** Cards, list rows, fields. */
    val surface1: Color,
    /** Sheets, bars, floating panels. */
    val surface2: Color,
    /** Pressed and chosen surfaces, the tracks of bars. */
    val surface3: Color,
    val border: Color,
    val borderSubtle: Color,
    val text: Color,
    val textMuted: Color,
    val textFaint: Color,
    val danger: Color,
    val dangerSoft: Color,
)

/** An accent's fill and the ink on it, and its text on dark and on light surfaces; the light theme may fill darker. */
private data class AccentTones(
    val fill: Long,
    val onFill: Long,
    val darkText: Long,
    val lightText: Long,
    val lightFill: Long = fill,
    val lightOnFill: Long = onFill,
)

private fun tones(accent: Accent): AccentTones = when (accent) {
    Accent.KODEX, Accent.DEVICE -> AccentTones(0xFFB1C6FE, 0xFF192F5D, 0xFFB1C6FE, 0xFF3E5285, 0xFF495D8F, 0xFFFFFFFF)
    Accent.AMBER -> AccentTones(0xFFF59E0B, 0xFF141416, 0xFFFBBF24, 0xFFB45309)
    Accent.CORAL -> AccentTones(0xFFFB7185, 0xFF1F1214, 0xFFFDA4AF, 0xFFBE123C)
    Accent.SKY -> AccentTones(0xFF38BDF8, 0xFF0B1A24, 0xFF7DD3FC, 0xFF0369A1)
    Accent.VIOLET -> AccentTones(0xFFA78BFA, 0xFF150F26, 0xFFC4B5FD, 0xFF6D28D9)
}

fun kodexColors(accent: Accent, dark: Boolean): KodexColors {
    val tone = tones(accent)
    return if (dark) {
        val fill = Color(tone.fill)
        val surface1 = Color(0xFF1B1B1F)
        KodexColors(
            dark = true,
            accent = fill, onAccent = Color(tone.onFill), accentText = Color(tone.darkText),
            accentSoft = fill.copy(alpha = 0.20f).compositeOver(surface1),
            offline = Color(0xFF6ED9C0), offlineText = Color(0xFF6ED9C0),
            offlineSoft = Color(0xFF6ED9C0).copy(alpha = 0.14f).compositeOver(surface1),
            background = Color(0xFF121316), surface1 = surface1, surface2 = Color(0xFF232428), surface3 = Color(0xFF2E2F33),
            border = Color(0xFF34363D), borderSubtle = Color(0xFF26272C),
            text = Color(0xFFE3E2E6), textMuted = Color(0xFFB4B6C2), textFaint = Color(0xFF7D7F89),
            danger = Color(0xFFFFB4AB), dangerSoft = Color(0xFF3C1B19),
        )
    } else {
        val fill = Color(tone.lightFill)
        val surface1 = Color(0xFFFFFFFF)
        KodexColors(
            dark = false,
            accent = fill, onAccent = Color(tone.lightOnFill), accentText = Color(tone.lightText),
            accentSoft = Color(tone.fill).copy(alpha = 0.22f).compositeOver(surface1),
            offline = Color(0xFF1FA88E), offlineText = Color(0xFF006B5A),
            offlineSoft = Color(0xFF1FA88E).copy(alpha = 0.14f).compositeOver(surface1),
            background = Color(0xFFF8F8FC), surface1 = surface1, surface2 = Color(0xFFF0F0F6), surface3 = Color(0xFFE3E3EB),
            border = Color(0xFFD7D8E1), borderSubtle = Color(0xFFE8E8EF),
            text = Color(0xFF1A1B20), textMuted = Color(0xFF4A4B55), textFaint = Color(0xFF8F909A),
            danger = Color(0xFFBA1A1A), dangerSoft = Color(0xFFFFDAD6),
        )
    }
}

/** The device's own colours (Material You) in Kodex's roles. */
@RequiresApi(Build.VERSION_CODES.S)
private fun deviceColors(context: Context, dark: Boolean): Pair<KodexColors, ColorScheme> {
    val scheme = if (dark) dynamicDarkColorScheme(context) else dynamicLightColorScheme(context)
    val base = kodexColors(Accent.KODEX, dark)
    val colors = base.copy(
        accent = scheme.primary, onAccent = scheme.onPrimary, accentText = scheme.primary,
        accentSoft = scheme.primaryContainer,
        background = scheme.background, surface1 = scheme.surfaceContainerLow, surface2 = scheme.surfaceContainer,
        surface3 = scheme.surfaceContainerHighest, border = scheme.outlineVariant, borderSubtle = scheme.surfaceContainerHigh,
        text = scheme.onSurface, textMuted = scheme.onSurfaceVariant,
    )
    return colors to scheme
}

private fun scheme(c: KodexColors): ColorScheme = if (c.dark) {
    darkColorScheme(
        primary = c.accent, onPrimary = c.onAccent, primaryContainer = c.accentSoft, onPrimaryContainer = c.accentText,
        inversePrimary = c.accentText,
        // The chosen chip, tab (and its label) and slider track take the accent; teal comes from KodexTheme.colors.
        secondary = c.accentText, onSecondary = c.onAccent, secondaryContainer = c.accentSoft, onSecondaryContainer = c.accentText,
        tertiary = c.accentText, onTertiary = c.onAccent,
        background = c.background, onBackground = c.text,
        surface = c.background, onSurface = c.text, surfaceVariant = c.surface3, onSurfaceVariant = c.textMuted,
        surfaceTint = Color.Transparent,
        inverseSurface = c.text, inverseOnSurface = c.background,
        error = c.danger, onError = Color(0xFF2A0A0A), errorContainer = c.dangerSoft, onErrorContainer = c.danger,
        outline = Color(0xFF8F909A), outlineVariant = c.border, scrim = Color.Black,
        surfaceBright = Color(0xFF38393C), surfaceDim = c.background,
        surfaceContainerLowest = Color(0xFF0D0E11), surfaceContainerLow = c.surface1, surfaceContainer = c.surface1,
        surfaceContainerHigh = c.surface2, surfaceContainerHighest = c.surface3,
    )
} else {
    lightColorScheme(
        primary = c.accent, onPrimary = c.onAccent, primaryContainer = c.accentSoft, onPrimaryContainer = c.accentText,
        inversePrimary = c.accent,
        secondary = c.accentText, onSecondary = Color.White, secondaryContainer = c.accentSoft, onSecondaryContainer = c.accentText,
        tertiary = c.accentText, onTertiary = Color.White,
        background = c.background, onBackground = c.text,
        surface = c.background, onSurface = c.text, surfaceVariant = c.surface3, onSurfaceVariant = c.textMuted,
        surfaceTint = Color.Transparent,
        inverseSurface = Color(0xFF2F3034), inverseOnSurface = Color(0xFFF1F0F4),
        error = c.danger, onError = Color.White, errorContainer = c.dangerSoft, onErrorContainer = c.danger,
        outline = Color(0xFF8F909A), outlineVariant = c.border, scrim = Color.Black,
        surfaceBright = c.surface1, surfaceDim = Color(0xFFDCDCE4),
        surfaceContainerLowest = Color.White, surfaceContainerLow = c.surface1, surfaceContainer = c.surface1,
        surfaceContainerHigh = c.surface2, surfaceContainerHighest = c.surface3,
    )
}

/** Everything in Roboto Flex: a variable font in res/font, cut to its weight axis (300–800) and Latin. */
val Flex = FontFamily(
    Font(R.font.roboto_flex, FontWeight.Light),
    Font(R.font.roboto_flex, FontWeight.Normal),
    Font(R.font.roboto_flex, FontWeight.Medium),
    Font(R.font.roboto_flex, FontWeight.SemiBold),
    Font(R.font.roboto_flex, FontWeight.Bold),
    Font(R.font.roboto_flex, FontWeight.ExtraBold),
)

private fun style(family: FontFamily, weight: FontWeight, size: Int, line: Int, spacing: Double) =
    TextStyle(fontFamily = family, fontWeight = weight, fontSize = size.sp, lineHeight = line.sp, letterSpacing = spacing.em)

val KodexTypography = Typography(
    displayLarge = style(Flex, FontWeight.ExtraBold, 40, 48, -0.02),
    displayMedium = style(Flex, FontWeight.Bold, 34, 42, -0.02),
    displaySmall = style(Flex, FontWeight.Bold, 30, 38, -0.015),
    headlineLarge = style(Flex, FontWeight.Bold, 28, 36, -0.015),
    headlineMedium = style(Flex, FontWeight.Bold, 24, 32, -0.01),
    headlineSmall = style(Flex, FontWeight.SemiBold, 20, 28, -0.005),
    titleLarge = style(Flex, FontWeight.SemiBold, 19, 26, 0.0),
    titleMedium = style(Flex, FontWeight.SemiBold, 15, 21, 0.0),
    titleSmall = style(Flex, FontWeight.Medium, 14, 19, 0.0),
    bodyLarge = style(Flex, FontWeight.Normal, 15, 22, 0.005),
    bodyMedium = style(Flex, FontWeight.Normal, 14, 20, 0.01),
    bodySmall = style(Flex, FontWeight.Normal, 12, 16, 0.01),
    labelLarge = style(Flex, FontWeight.Medium, 14, 18, 0.01),
    labelMedium = style(Flex, FontWeight.Medium, 12, 16, 0.02),
    labelSmall = style(Flex, FontWeight.Bold, 10, 14, 0.08),
)

val KodexShapes = Shapes(
    extraSmall = RoundedCornerShape(6.dp),
    small = RoundedCornerShape(8.dp),
    medium = RoundedCornerShape(16.dp),
    large = RoundedCornerShape(20.dp),
    extraLarge = RoundedCornerShape(28.dp),
)

val LocalKodexColors = staticCompositionLocalOf { kodexColors(Accent.KODEX, dark = true) }

/** Kodex's colours beyond Material's roles, as `KodexTheme.colors`. */
object KodexTheme {
    val colors: KodexColors
        @Composable @ReadOnlyComposable get() = LocalKodexColors.current
}

@Composable
fun isDark(choice: ThemeChoice): Boolean = when (choice) {
    ThemeChoice.SYSTEM -> isSystemInDarkTheme()
    ThemeChoice.LIGHT -> false
    ThemeChoice.DARK -> true
}

@Composable
fun KodexTheme(choice: ThemeChoice = ThemeChoice.SYSTEM, accent: Accent = Accent.KODEX, content: @Composable () -> Unit) {
    val dark = isDark(choice)
    val context = LocalContext.current
    val (colors, scheme) = remember(dark, accent, context) {
        if (accent == Accent.DEVICE && Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            deviceColors(context, dark)
        } else {
            kodexColors(accent, dark).let { it to scheme(it) }
        }
    }
    SystemBarIcons(dark)
    CompositionLocalProvider(LocalKodexColors provides colors) {
        MaterialTheme(colorScheme = scheme, typography = KodexTypography, shapes = KodexShapes, content = content)
    }
}

/** Dark icons in the status and navigation bars over the light theme, light ones over the dark. */
@Composable
private fun SystemBarIcons(dark: Boolean) {
    val view = LocalView.current
    if (view.isInEditMode) return
    SideEffect {
        val window = (view.context as? Activity)?.window ?: return@SideEffect
        WindowCompat.getInsetsController(window, view).apply {
            isAppearanceLightStatusBars = !dark
            isAppearanceLightNavigationBars = !dark
        }
    }
}
