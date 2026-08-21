package com.example.data.api

import android.content.Context
import com.example.BuildConfig
import android.content.SharedPreferences
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

class TokenManager(context: Context) {
    private val prefs: SharedPreferences = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)

    private val _tokenFlow = MutableStateFlow(prefs.getString(KEY_TOKEN, null))
    val tokenFlow: StateFlow<String?> = _tokenFlow.asStateFlow()

    private val _baseUrlFlow = MutableStateFlow(prefs.getString(KEY_BASE_URL, DEFAULT_BASE_URL) ?: DEFAULT_BASE_URL)
    val baseUrlFlow: StateFlow<String> = _baseUrlFlow.asStateFlow()

    fun getToken(): String? = prefs.getString(KEY_TOKEN, null)
    fun getRefreshToken(): String? = prefs.getString(KEY_REFRESH_TOKEN, null)

    fun saveToken(token: String) {
        prefs.edit().putString(KEY_TOKEN, token).commit()
        _tokenFlow.value = token
    }

    fun saveRefreshToken(token: String?) {
        if (token != null) {
            prefs.edit().putString(KEY_REFRESH_TOKEN, token).commit()
        }
    }

    fun clearTokens() {
        prefs.edit().remove(KEY_TOKEN).remove(KEY_REFRESH_TOKEN).commit()
        _tokenFlow.value = null
    }

    fun getBaseUrl(): String = prefs.getString(KEY_BASE_URL, DEFAULT_BASE_URL) ?: DEFAULT_BASE_URL

    fun getRootUrl(): String {
        val base = getBaseUrl()
        return if (base.contains("/api/")) {
            base.substringBefore("/api/")
        } else {
            base.trimEnd('/')
        }
    }

    fun saveBaseUrl(url: String) {
        val formattedUrl = if (!url.endsWith("/")) "$url/" else url
        prefs.edit().putString(KEY_BASE_URL, formattedUrl).commit()
        _baseUrlFlow.value = formattedUrl
    }

    fun saveUser(id: String, email: String, name: String, role: String) {
        prefs.edit()
            .putString(KEY_USER_ID, id)
            .putString(KEY_USER_EMAIL, email)
            .putString(KEY_USER_NAME, name)
            .putString(KEY_USER_ROLE, role)
            .commit()
    }

    fun getUserId(): String? = prefs.getString(KEY_USER_ID, null)
    fun getUserEmail(): String = prefs.getString(KEY_USER_EMAIL, "admin@carrental.com") ?: "admin@carrental.com"
    fun getUserName(): String = prefs.getString(KEY_USER_NAME, "Administrateur") ?: "Administrateur"
    fun getUserRole(): String = prefs.getString(KEY_USER_ROLE, "ADMIN") ?: "ADMIN"

    fun clearAll() {
        prefs.edit().clear().commit()
        _tokenFlow.value = null
    }

    companion object {
        private const val PREFS_NAME = "car_rental_auth_prefs"
        private const val KEY_TOKEN = "jwt_access_token"
        private const val KEY_REFRESH_TOKEN = "jwt_refresh_token"
        private const val KEY_BASE_URL = "api_base_url"
        private const val KEY_USER_ID = "user_id"
        private const val KEY_USER_EMAIL = "user_email"
        private const val KEY_USER_NAME = "user_name"
        private const val KEY_USER_ROLE = "user_role"

        val DEFAULT_BASE_URL = BuildConfig.API_BASE_URL
    }
}
