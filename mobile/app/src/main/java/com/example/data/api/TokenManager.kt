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

    init {
        val current = prefs.getString(KEY_BASE_URL, null)
        if (current != null) {
            val isEmulatorUrl = current.contains("10.0.2.2") || current.contains("127.0.0.1") || current.contains("localhost")
            val isLanUrl = current.contains("192.168") || current.contains("10.0.0") || current.startsWith("http://")
            
            val shouldReset = isEmulatorUrl || isLanUrl || current.contains("ngrok")
            
            if (shouldReset) {
                prefs.edit().putString(KEY_BASE_URL, DEFAULT_BASE_URL).apply()
                _baseUrlFlow.value = DEFAULT_BASE_URL
            }
        }
    }


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
    fun getUserEmail(): String = prefs.getString(KEY_USER_EMAIL, "") ?: ""
    fun getUserName(): String = prefs.getString(KEY_USER_NAME, "") ?: ""
    fun getUserRole(): String = prefs.getString(KEY_USER_ROLE, "ADMIN") ?: "ADMIN"

    // Strict identity accessors: values previously persisted from a SERVER
    // login response only. No fabricated defaults — null means "unknown".
    fun getStoredUserEmail(): String? = prefs.getString(KEY_USER_EMAIL, null)
    fun getStoredUserName(): String = prefs.getString(KEY_USER_NAME, "") ?: ""
    fun getStoredUserRole(): String? = prefs.getString(KEY_USER_ROLE, null)

    /**
     * Clear the authenticated session (tokens + user identity) while KEEPING
     * non-credential device configuration such as the API base URL. This is the
     * correct reset for logout and for a server-confirmed dead session — wiping
     * the base URL on every session drop was a bug (it silently reverted the
     * server the operator had configured).
     */
    fun clearSession() {
        prefs.edit()
            .remove(KEY_TOKEN)
            .remove(KEY_REFRESH_TOKEN)
            .remove(KEY_USER_ID)
            .remove(KEY_USER_EMAIL)
            .remove(KEY_USER_NAME)
            .remove(KEY_USER_ROLE)
            .commit()
        _tokenFlow.value = null
    }

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
