package com.example.data.api

/**
 * Maps an authentication HTTP failure onto the message shown on the login
 * screen.
 *
 * The backend is authoritative. This mapper branches on the HTTP status code
 * and the machine-readable `error_code` the backend sends — never on the words
 * inside the localized message. The previous implementation searched the raw
 * body for "lock"/"bloqu"/"verrou", which matched unrelated text (any body
 * containing "blocked", "clock", "unlock", an HTML error page from a proxy)
 * and missed the Arabic lockout message entirely.
 *
 * Contract (backend/app/api/v1/auth.py::_auth_failure_response):
 *   200 -> success
 *   401 -> invalid credentials              (error_code = INVALID_CREDENTIALS)
 *   403 -> account disabled                 (error_code = ACCOUNT_DISABLED)
 *   429 + error_code = ACCOUNT_LOCKED  -> temporary account lockout
 *          (+ retry_after_seconds = the server's own remaining time)
 *   429 without that error_code        -> per-IP rate limit
 *   5xx -> server failure
 *
 * The lockout message is emitted for exactly one reason: the server said
 * ACCOUNT_LOCKED. A 401, a timeout, a 5xx, a malformed body or an expired JWT
 * can never produce it.
 */
object AuthErrorMapper {

    const val CODE_ACCOUNT_LOCKED = "ACCOUNT_LOCKED"
    const val CODE_ACCOUNT_DISABLED = "ACCOUNT_DISABLED"

    // Deliberately regex-based rather than JSON-parsed: the error body is a
    // tiny flat object, and this keeps the mapper a pure Kotlin function with
    // no org.json/Moshi dependency, so it is unit-testable on the JVM.
    private val ERROR_CODE_RE = Regex("\"error_code\"\\s*:\\s*\"([A-Z_]+)\"")
    private val RETRY_AFTER_RE = Regex("\"retry_after_seconds\"\\s*:\\s*(\\d+)")

    fun errorCodeOf(rawBody: String?): String? =
        rawBody?.let { ERROR_CODE_RE.find(it)?.groupValues?.get(1) }

    fun retryAfterSecondsOf(rawBody: String?, header: String? = null): Int? {
        val fromBody = rawBody?.let { RETRY_AFTER_RE.find(it)?.groupValues?.get(1)?.toIntOrNull() }
        return fromBody ?: header?.trim()?.toIntOrNull()
    }

    /**
     * Human-readable remaining delay, built from the server's value only.
     * The client never invents a duration: with no server value it says the
     * account is temporarily locked without promising a time.
     */
    fun formatRetryDelay(seconds: Int?): String = when {
        seconds == null || seconds <= 0 -> "Réessayez plus tard."
        seconds < 60 -> "Réessayez dans moins d'une minute."
        else -> {
            val minutes = (seconds + 59) / 60
            "Réessayez dans $minutes minute${if (minutes > 1) "s" else ""}."
        }
    }

    fun map(httpCode: Int, rawBody: String?, retryAfterHeader: String? = null): String {
        val errorCode = errorCodeOf(rawBody)

        // A lockout is reported by code, never guessed from the message text.
        // 401 is accepted alongside 429 purely for version tolerance: an app
        // built after this change must still behave correctly if it is pointed
        // at a backend that has not been redeployed yet.
        if (errorCode == CODE_ACCOUNT_LOCKED) {
            val delay = formatRetryDelay(retryAfterSecondsOf(rawBody, retryAfterHeader))
            return "Compte temporairement bloqué après plusieurs tentatives. $delay"
        }

        if (errorCode == CODE_ACCOUNT_DISABLED) {
            return "Ce compte est désactivé. Contactez un administrateur."
        }

        return when {
            httpCode == 401 || httpCode == 404 -> "E-mail ou mot de passe incorrect."
            httpCode == 403 -> "Accès refusé. Rôle non autorisé."
            httpCode == 429 -> "Trop de tentatives. Patientez une minute avant de réessayer."
            httpCode >= 500 -> "Le serveur a rencontré une erreur. Réessayez dans un instant."
            else -> "Erreur de connexion au serveur ($httpCode)."
        }
    }
}
