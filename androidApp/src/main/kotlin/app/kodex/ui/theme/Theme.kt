package app.kodex.ui.theme

import android.app.Activity
import android.content.Context
import android.os.Build
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
 * Kodex's own look: a deep charcoal canvas (or warm paper in the light theme) where the covers
 * give the colour, one accent for what is active (amber unless the user picks another, or the
 * device's own), and teal for what is on the device. Surfaces step up in lightness instead of
 * casting shadows, with a hairline border.
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

private data class AccentTones(val fill: Long, val onFill: Long, val darkText: Long, val lightText: Long)

private fun tones(accent: Accent): AccentTones = when (accent) {
    Accent.CORAL -> AccentTones(0xFFFB7185, 0xFF1F1214, 0xFFFDA4AF, 0xFFBE123C)
    Accent.SKY -> AccentTones(0xFF38BDF8, 0xFF0B1A24, 0xFF7DD3FC, 0xFF0369A1)
    Accent.VIOLET -> AccentTones(0xFFA78BFA, 0xFF150F26, 0xFFC4B5FD, 0xFF6D28D9)
    Accent.AMBER, Accent.DEVICE -> AccentTones(0xFFF59E0B, 0xFF141416, 0xFFFBBF24, 0xFFB45309)
}

fun kodexColors(accent: Accent, dark: Boolean): KodexColors {
    val tone = tones(accent)
    val fill = Color(tone.fill)
    return if (dark) {
        val surface1 = Color(0xFF1A1A1E)
        KodexColors(
            dark = true,
            accent = fill, onAccent = Color(tone.onFill), accentText = Color(tone.darkText),
            accentSoft = fill.copy(alpha = 0.16f).compositeOver(surface1),
            offline = Color(0xFF14B8A6), offlineText = Color(0xFF2DD4BF),
            offlineSoft = Color(0xFF14B8A6).copy(alpha = 0.16f).compositeOver(surface1),
            background = Color(0xFF121214), surface1 = surface1, surface2 = Color(0xFF222228), surface3 = Color(0xFF2D2D35),
            border = Color(0xFF2D2D35), borderSubtle = Color(0xFF23232A),
            text = Color(0xFFF3F4F6), textMuted = Color(0xFF9CA3AF), textFaint = Color(0xFF5E5E68),
            danger = Color(0xFFF87171), dangerSoft = Color(0xFF3A1517),
        )
    } else {
        val surface1 = Color(0xFFFFFFFF)
        KodexColors(
            dark = false,
            accent = fill, onAccent = Color(tone.onFill), accentText = Color(tone.lightText),
            accentSoft = fill.copy(alpha = 0.16f).compositeOver(surface1),
            offline = Color(0xFF14B8A6), offlineText = Color(0xFF0F766E),
            offlineSoft = Color(0xFF14B8A6).copy(alpha = 0.14f).compositeOver(surface1),
            background = Color(0xFFF7F5F2), surface1 = surface1, surface2 = Color(0xFFF0EDE8), surface3 = Color(0xFFE6E2DB),
            border = Color(0xFFDDD8D0), borderSubtle = Color(0xFFEAE6E0),
            text = Color(0xFF18181B), textMuted = Color(0xFF5B5B66), textFaint = Color(0xFFA1A1AA),
            danger = Color(0xFFB91C1C), dangerSoft = Color(0xFFFDE7E7),
        )
    }
}

/** The device's own colours (Material You) in Kodex's roles. */
private fun deviceColors(context: Context, dark: Boolean): Pair<KodexColors, ColorScheme> {
    val scheme = if (dark) dynamicDarkColorScheme(context) else dynamicLightColorScheme(context)
    val base = kodexColors(Accent.AMBER, dark)
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
        // The chosen chip, tab and slider track take the accent; teal comes from KodexTheme.colors.
        secondary = c.offline, onSecondary = Color(0xFF04201D), secondaryContainer = c.accentSoft, onSecondaryContainer = c.accentText,
        tertiary = c.accentText, onTertiary = c.onAccent,
        background = c.background, onBackground = c.text,
        surface = c.background, onSurface = c.text, surfaceVariant = c.surface3, onSurfaceVariant = c.textMuted,
        surfaceTint = Color.Transparent,
        inverseSurface = c.text, inverseOnSurface = c.background,
        error = c.danger, onError = Color(0xFF2A0A0A), errorContainer = c.dangerSoft, onErrorContainer = c.danger,
        outline = Color(0xFF4A4A55), outlineVariant = c.border, scrim = Color.Black,
        surfaceBright = Color(0xFF39393F), surfaceDim = c.background,
        surfaceContainerLowest = Color(0xFF0D0D0F), surfaceContainerLow = c.surface1, surfaceContainer = c.surface1,
        surfaceContainerHigh = c.surface2, surfaceContainerHighest = c.surface3,
    )
} else {
    lightColorScheme(
        primary = c.accent, onPrimary = c.onAccent, primaryContainer = c.accentSoft, onPrimaryContainer = c.accentText,
        inversePrimary = c.accent,
        secondary = c.offlineText, onSecondary = Color.White, secondaryContainer = c.accentSoft, onSecondaryContainer = c.accentText,
        tertiary = c.accentText, onTertiary = Color.White,
        background = c.background, onBackground = c.text,
        surface = c.background, onSurface = c.text, surfaceVariant = c.surface3, onSurfaceVariant = c.textMuted,
        surfaceTint = Color.Transparent,
        inverseSurface = Color(0xFF26262B), inverseOnSurface = Color(0xFFF3F4F6),
        error = c.danger, onError = Color.White, errorContainer = c.dangerSoft, onErrorContainer = c.danger,
        outline = Color(0xFFB9B3AA), outlineVariant = c.border, scrim = Color.Black,
        surfaceBright = c.surface1, surfaceDim = Color(0xFFE3DFD8),
        surfaceContainerLowest = Color.White, surfaceContainerLow = c.surface1, surfaceContainer = c.surface1,
        surfaceContainerHigh = c.surface2, surfaceContainerHighest = c.surface3,
    )
}

/** Titles in Plus Jakarta Sans, everything else in Inter (both variable fonts, in res/font). */
val Jakarta = FontFamily(
    Font(R.font.plus_jakarta_sans, FontWeight.SemiBold),
    Font(R.font.plus_jakarta_sans, FontWeight.Bold),
    Font(R.font.plus_jakarta_sans, FontWeight.ExtraBold),
)

val Inter = FontFamily(
    Font(R.font.inter, FontWeight.Normal),
    Font(R.font.inter, FontWeight.Medium),
    Font(R.font.inter, FontWeight.SemiBold),
    Font(R.font.inter, FontWeight.Bold),
)

private fun style(family: FontFamily, weight: FontWeight, size: Int, line: Int, spacing: Double) =
    TextStyle(fontFamily = family, fontWeight = weight, fontSize = size.sp, lineHeight = line.sp, letterSpacing = spacing.em)

val KodexTypography = Typography(
    displayLarge = style(Jakarta, FontWeight.ExtraBold, 40, 48, -0.02),
    displayMedium = style(Jakarta, FontWeight.ExtraBold, 34, 42, -0.02),
    displaySmall = style(Jakarta, FontWeight.ExtraBold, 30, 38, -0.02),
    headlineLarge = style(Jakarta, FontWeight.Bold, 28, 36, -0.02),
    headlineMedium = style(Jakarta, FontWeight.Bold, 24, 32, -0.02),
    headlineSmall = style(Jakarta, FontWeight.Bold, 21, 28, -0.01),
    titleLarge = style(Jakarta, FontWeight.Bold, 19, 26, -0.01),
    titleMedium = style(Inter, FontWeight.SemiBold, 15, 21, 0.0),
    titleSmall = style(Inter, FontWeight.SemiBold, 14, 19, 0.0),
    bodyLarge = style(Inter, FontWeight.Normal, 15, 22, 0.01),
    bodyMedium = style(Inter, FontWeight.Normal, 14, 20, 0.01),
    bodySmall = style(Inter, FontWeight.Normal, 12, 16, 0.01),
    labelLarge = style(Inter, FontWeight.SemiBold, 14, 18, 0.01),
    labelMedium = style(Inter, FontWeight.SemiBold, 12, 16, 0.02),
    labelSmall = style(Inter, FontWeight.Bold, 10, 14, 0.06),
)

val KodexShapes = Shapes(
    extraSmall = RoundedCornerShape(6.dp),
    small = RoundedCornerShape(8.dp),
    medium = RoundedCornerShape(12.dp),
    large = RoundedCornerShape(16.dp),
    extraLarge = RoundedCornerShape(24.dp),
)

val LocalKodexColors = staticCompositionLocalOf { kodexColors(Accent.AMBER, dark = true) }

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
fun KodexTheme(choice: ThemeChoice = ThemeChoice.SYSTEM, accent: Accent = Accent.AMBER, content: @Composable () -> Unit) {
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
