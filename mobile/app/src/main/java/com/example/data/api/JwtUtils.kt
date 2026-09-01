package com.example.data.api

import android.util.Base64
import org.json.JSONObject

/**
 * Minimal, dependency-free JWT inspection.
 *
 * Used ONLY for a local, best-effort "is this token obviously expired?" check
 * during offline session restore. It never replaces server validation — a token
 * that looks valid locally is still confirmed against the backend whenever the
 * network is reachable. Its only job is to stop us from unlocking the app with a
 * token we can already prove is dead while offline.
 */
object JwtUtils {

    /** Unix epoch seconds of the token's `exp` claim, or null if unreadable. */
    fun expiresAtEpochSeconds(token: String?): Long? {
        if (token.isNullOrBlank()) return null
        return try {
            val parts = token.split(".")
            if (parts.size < 2) return null
            val payload = String(
                Base64.decode(parts[1], Base64.URL_SAFE or Base64.NO_PADDING or Base64.NO_WRAP)
            )
            val exp = JSONObject(payload).optLong("exp", 0L)
            if (exp > 0L) exp else null
        } catch (e: Throwable) {
            null
        }
    }

    /**
     * True only when we can read an `exp` claim AND it is in the past (minus a
     * small skew). Unreadable tokens return false — "unknown", not "expired" —
     * so the server stays the authority.
     */
    fun isDefinitelyExpired(token: String?, skewSeconds: Long = 30L): Boolean {
        val exp = expiresAtEpochSeconds(token) ?: return false
        return exp <= (System.currentTimeMillis() / 1000L) - skewSeconds
    }

    /** True when the token has a readable `exp` that is still in the future. */
    fun isProbablyValid(token: String?): Boolean {
        val exp = expiresAtEpochSeconds(token) ?: return false
        return exp > (System.currentTimeMillis() / 1000L)
    }
}
