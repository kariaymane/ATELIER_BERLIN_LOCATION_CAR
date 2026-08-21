package com.example.data.repository

import com.example.data.api.ApiClient
import com.example.data.api.LoginRequestDto
import com.example.data.api.TokenManager
import com.example.data.model.UserSession
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.withContext

class AuthRepository(
    private val apiClient: ApiClient,
    private val tokenManager: TokenManager
) {
    private val _currentUserSession = MutableStateFlow<UserSession?>(null)
    val currentUserSession: StateFlow<UserSession?> = _currentUserSession.asStateFlow()

    init {
        restoreSession()
    }

    fun restoreSession() {
        val token = tokenManager.getToken()
        if (!token.isNullOrBlank()) {
            val email = tokenManager.getUserEmail()
            val name = tokenManager.getUserName()
            val role = tokenManager.getUserRole()
            val id = tokenManager.getUserId() ?: "u1"
            val initials = name.split(" ")
                .mapNotNull { it.firstOrNull()?.uppercase() }
                .take(2)
                .joinToString("")
                .ifEmpty { "SE" }

            _currentUserSession.value = UserSession(
                id = id,
                email = email,
                name = name,
                role = role,
                token = token,
                initials = initials
            )
        } else {
            _currentUserSession.value = null
        }
    }

    suspend fun login(email: String, password: String): Result<UserSession> = withContext(Dispatchers.IO) {
        try {
            val response = apiClient.getService().login(
                LoginRequestDto(email = email.trim(), password = password)
            )

            if (response.isSuccessful && response.body() != null) {
                val body = response.body()!!
                tokenManager.saveToken(body.accessToken)
                tokenManager.saveRefreshToken(body.refreshToken)
                val userId = body.user?.id ?: body.userId ?: "user-1"
                val userEmail = body.user?.email ?: email.trim()
                val userRole = body.user?.role ?: body.role ?: "ADMIN"
                val fullName = body.fullName ?: listOfNotNull(body.user?.firstName, body.user?.lastName)
                    .joinToString(" ")
                    .ifBlank { userEmail.substringBefore("@").replaceFirstChar { it.uppercase() } }

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
        } catch (e: Exception) {
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

    fun logout() {
        tokenManager.clearTokens()
        _currentUserSession.value = null
    }

    fun updateBaseUrl(newUrl: String) {
        tokenManager.saveBaseUrl(newUrl)
    }

    fun getBaseUrl(): String = tokenManager.getBaseUrl()
}
