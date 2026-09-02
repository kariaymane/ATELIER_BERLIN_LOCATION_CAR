package com.example.data.repository

import android.util.Log
import com.example.data.api.ApiClient
import com.example.data.api.JwtUtils
import com.example.data.api.LoginRequestDto
import com.example.data.api.RefreshRequestDto
import com.example.data.api.TokenManager
import com.example.data.model.UserSession
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.withContext

/**
 * Authentication repository.
 *
 * Security / session contract:
 *  - The backend is the single source of truth. Whenever the network is
 *    reachable, session restore validates against the server (refresh-token
 *    flow, falling back to an authenticated probe).
 *  - The session is treated as dead ONLY when the server explicitly rejects it
 *    (HTTP 401/403 on refresh or probe) or the user logs out. A network failure,
 *    timeout, or 5xx is NOT a rejection.
 *  - Offline / server-unreachable start: if a locally-persisted session exists
 *    and its stored token is not already provably expired, the app opens with
 *    that cached session and re-validates in the background on the next
 *    reachable call. "Log in once, stay logged in until logout."
 *  - User identity comes only from server responses or identity previously
 *    persisted from a server response. No fabricated defaults.
 *  - Logout clears tokens and identity (keeps the configured base URL); the
 *    next start requires email + password again.
 */
class AuthRepository(
    private val apiClient: ApiClient,
    private val tokenManager: TokenManager
) {
    private val _currentUserSession = MutableStateFlow<UserSession?>(null)
    val currentUserSession: StateFlow<UserSession?> = _currentUserSession.asStateFlow()

    private val _restoring = MutableStateFlow(false)
    val restoring: StateFlow<Boolean> = _restoring.asStateFlow()

    /**
     * Called at app start (during Splash). Validates any stored session
     * against the backend before the user may enter the application.
     */
    suspend fun validateAndRestoreSession() {
        _restoring.value = true
        try {
            val access = tokenManager.getToken()
            val refresh = tokenManager.getRefreshToken()
            if (access.isNullOrBlank() && refresh.isNullOrBlank()) {
                clearLocalSession()
                return
            }

            // A cached session we could fall back to if the server is
            // unreachable: identity must be present, and at least one stored
            // token must not already be provably expired.
            val offlineSession: UserSession? =
                buildSessionFromStoredIdentity(token = access ?: refresh ?: "")
                    ?.takeIf {
                        !JwtUtils.isDefinitelyExpired(refresh) ||
                            !JwtUtils.isDefinitelyExpired(access)
                    }

            // Preferred path: the server verifies the refresh token.
            if (!refresh.isNullOrBlank()) {
                val refreshed = withContext(Dispatchers.IO) {
                    try {
                        apiClient.getService()
                            .refreshToken(RefreshRequestDto(refreshToken = refresh))
                    } catch (e: Throwable) {
                        Log.w("AUTH", "restore refresh network failure: ${e.message}")
                        null
                    }
                }
                val body = refreshed?.body()
                if (refreshed?.isSuccessful == true && body != null && body.accessToken.isNotBlank()) {
                    tokenManager.saveToken(body.accessToken)
                    if (body.refreshToken.isNotBlank()) {
                        tokenManager.saveRefreshToken(body.refreshToken)
                    }
                    val session = buildSessionFromStoredIdentity(token = body.accessToken)
                    if (session != null) {
                        _currentUserSession.value = session
                        return
                    }
                    clearLocalSession()
                    return
                }
                // Server was reached and explicitly rejected the refresh token
                // (401/403) -> the session is genuinely dead.
                if (refreshed != null && refreshed.code() in intArrayOf(401, 403)) {
                    clearLocalSession()
                    return
                }
                // Server unreachable, timed out, or returned a transient error
                // (5xx / rate limit). Do NOT destroy the session over a network
                // condition: open with the cached session if we have one and it
                // is not already expired; the next reachable call re-validates.
                if (offlineSession != null) {
                    Log.i("AUTH", "server unreachable on restore -> entering with cached session")
                    _currentUserSession.value = offlineSession
                    return
                }
                clearLocalSession()
                return
            }

            // No refresh token: probe an authenticated endpoint with the
            // stored access token.
            val probe = withContext(Dispatchers.IO) {
                try {
                    apiClient.getService().getDashboardStats()
                } catch (e: Throwable) {
                    Log.w("AUTH", "restore probe network failure: ${e.message}")
                    null
                }
            }
            if (probe?.isSuccessful == true) {
                val session = buildSessionFromStoredIdentity(token = access!!)
                if (session != null) {
                    _currentUserSession.value = session
                    return
                }
                clearLocalSession()
                return
            }
            if (probe != null && probe.code() in intArrayOf(401, 403)) {
                clearLocalSession()
                return
            }
            if (offlineSession != null) {
                Log.i("AUTH", "server unreachable on restore -> entering with cached session")
                _currentUserSession.value = offlineSession
                return
            }
            clearLocalSession()
        } finally {
            _restoring.value = false
        }
    }

    /**
     * Build a session strictly from identity previously persisted from a
     * server login response. Returns null when identity is missing — the
     * user must sign in again (never fabricate identity).
     */
    private fun buildSessionFromStoredIdentity(token: String): UserSession? {
        val id = tokenManager.getUserId()
        val email = tokenManager.getStoredUserEmail()
        val name = tokenManager.getStoredUserName()
        val role = tokenManager.getStoredUserRole()
        if (id.isNullOrBlank() || email.isNullOrBlank() || role.isNullOrBlank()) {
            return null
        }
        val initials = name.split(" ")
            .mapNotNull { it.firstOrNull()?.uppercase() }
            .take(2)
            .joinToString("")
            .ifEmpty { "SE" }
        return UserSession(
            id = id,
            email = email,
            name = name,
            role = role,
            token = token,
            initials = initials
        )
    }

    /**
     * SECURITY: `password` is used for exactly one thing — the request body of
     * the `/auth/login` call. It is NOT stored: no field, no TokenManager key,
     * no SharedPreferences, no Room, no log. The [LoginRequestDto] that carries
     * it is a local value that becomes unreachable when this function returns;
     * only the returned access/refresh tokens are persisted (by TokenManager).
     * The plaintext password never leaves this method.
     */
    suspend fun login(email: String, password: String): Result<UserSession> = withContext(Dispatchers.IO) {
        try {
            val response = apiClient.getService().login(
                LoginRequestDto(email = email.trim(), password = password)
            )

            if (response.isSuccessful && response.body() != null) {
                val body = response.body()!!
                // Identity MUST come from the server. No defaults, no fallbacks.
                val userId = body.userId
                val userRole = body.role
                if (userId.isNullOrBlank() || userRole.isNullOrBlank()) {
                    return@withContext Result.failure<UserSession>(
                        Exception("Réponse d'authentification du serveur invalide.")
                    )
                }
                tokenManager.saveToken(body.accessToken)
                body.refreshToken?.takeIf { it.isNotBlank() }?.let {
                    tokenManager.saveRefreshToken(it)
                }
                val userEmail = body.user?.email ?: email.trim()
                val fullName = body.fullName?.takeIf { it.isNotBlank() }
                    ?: userEmail.substringBefore("@").replaceFirstChar { it.uppercase() }

                tokenManager.saveUser(
                    id = userId,
                    email = userEmail,
                    name = fullName,
                    role = userRole
                )

                val initials = fullName.split(" ")
                    .mapNotNull { it.firstOrNull()?.uppercase() }
                    .take(2)
                    .joinToString("")
                    .ifEmpty { "SE" }

                val session = UserSession(
                    id = userId,
                    email = userEmail,
                    name = fullName,
                    role = userRole,
                    token = body.accessToken,
                    initials = initials
                )

                _currentUserSession.value = session
                Result.success(session)
            } else {
                val errorMsg = when (response.code()) {
                    401, 404 -> "Identifiants incorrects"
                    403 -> "Accès refusé. Rôle non autorisé."
                    429 -> "Trop de tentatives. Veuillez patienter une minute."
                    else -> "Erreur de connexion au serveur (${response.code()})."
                }
                Result.failure(Exception(errorMsg))
            }
        } catch (e: Throwable) {
            val msg = if (e.message?.contains("Unable to resolve host") == true ||
                          e.message?.contains("Failed to connect") == true ||
                          e.message?.contains("ConnectException") == true ||
                          e.message?.contains("SocketTimeoutException") == true) {
                "Impossible de contacter le serveur."
            } else {
                e.localizedMessage ?: "Impossible de contacter le serveur."
            }
            Result.failure(Exception(msg))
        }
    }

    /**
     * Logout: clear tokens and identity locally and invalidate the refresh
     * token server-side (best effort). The next start requires email +
     * password.
     */
    suspend fun logout() = withContext(Dispatchers.IO) {
        val refresh = tokenManager.getRefreshToken()
        val access = tokenManager.getToken()
        if (!refresh.isNullOrBlank() && !access.isNullOrBlank()) {
            try {
                apiClient.getService().logout(
                    com.example.data.api.LogoutRequestDto(refreshToken = refresh),
                    "Bearer $access"
                )
            } catch (e: Throwable) {
                Log.w("AUTH", "server logout skipped: ${e.message}")
            }
        }
        clearLocalSession()
    }

    private fun clearLocalSession() {
        tokenManager.clearSession()
        _currentUserSession.value = null
    }

    fun updateBaseUrl(newUrl: String) {
        tokenManager.saveBaseUrl(newUrl)
    }

    fun getBaseUrl(): String = tokenManager.getBaseUrl()
}
