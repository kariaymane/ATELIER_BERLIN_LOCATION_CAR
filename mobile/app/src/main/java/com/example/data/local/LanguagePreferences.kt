package com.example.data.local

import android.content.Context
import android.content.SharedPreferences

enum class AppLanguage(val code: String, val displayName: String, val nativeName: String) {
    FR("fr", "Français", "Français"),
    AR("ar", "Arabe", "العربية")
}

class LanguagePreferences(context: Context) {
    private val prefs: SharedPreferences = context.getSharedPreferences("language_prefs", Context.MODE_PRIVATE)

    var language: AppLanguage
        get() {
            val code = prefs.getString("app_language", AppLanguage.FR.name) ?: AppLanguage.FR.name
            return try {
                AppLanguage.valueOf(code)
            } catch (e: Exception) {
                AppLanguage.FR
            }
        }
        set(value) = prefs.edit().putString("app_language", value.name).apply()
}
