package com.example.ui.theme

import android.app.Activity
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.SideEffect
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.toArgb
import androidx.compose.ui.platform.LocalView
import androidx.core.view.WindowCompat

import androidx.compose.material3.darkColorScheme

private val LightColorScheme = lightColorScheme(
    primary = ExecutivePrimaryGreen,
    onPrimary = Color.White,
    primaryContainer = ExecutiveSurfaceVariant,
    onPrimaryContainer = ExecutivePrimaryGreenDark,
    secondary = ExecutiveGold,
    onSecondary = Color.White,
    secondaryContainer = StatusGoldBg,
    onSecondaryContainer = StatusGoldText,
    background = ExecutiveBackground,
    onBackground = ExecutiveTextPrimary,
    surface = ExecutiveSurface,
    onSurface = ExecutiveTextPrimary,
    surfaceVariant = ExecutiveSurfaceVariant,
    onSurfaceVariant = ExecutiveTextSecondary,
    outline = ExecutiveBorder,
    outlineVariant = ExecutiveBorderLight
)

private val DarkColorScheme = darkColorScheme(
    primary = Color(0xFFB5CDB0),
    onPrimary = Color(0xFF143626),
    primaryContainer = Color(0xFF276147),
    onPrimaryContainer = Color.White,
    secondary = ExecutiveGoldLight,
    onSecondary = Color(0xFF1C1018),
    background = Color(0xFF121212),
    onBackground = Color(0xFFF4F4F5),
    surface = Color(0xFF1E1E1E),
    onSurface = Color(0xFFF4F4F5),
    surfaceVariant = Color(0xFF2C2C2C),
    onSurfaceVariant = Color(0xFFA1A1AA),
    outline = Color(0xFF3F3F46),
    outlineVariant = Color(0xFF27272A)
)

@Composable
fun MyApplicationTheme(
    darkTheme: Boolean = isSystemInDarkTheme(),
    content: @Composable () -> Unit
) {
    val colorScheme = if (darkTheme) DarkColorScheme else LightColorScheme

    val view = LocalView.current
    if (!view.isInEditMode) {
        SideEffect {
            val window = (view.context as Activity).window
            WindowCompat.getInsetsController(window, view).apply {
                isAppearanceLightStatusBars = !darkTheme
                isAppearanceLightNavigationBars = !darkTheme
            }
        }
    }

    MaterialTheme(
        colorScheme = colorScheme,
        typography = Typography,
        content = content
    )
}
