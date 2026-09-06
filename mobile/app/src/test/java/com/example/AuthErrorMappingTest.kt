package com.example

import com.example.data.api.AuthErrorMapper
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * The login screen must show "compte bloqué" for exactly one reason: the
 * server said ACCOUNT_LOCKED. Everything else — a wrong password, a timeout,
 * a 500, a malformed body, an expired token, a proxy error page — must read as
 * its own real cause.
 */
class AuthErrorMappingTest {

    private fun isLockoutText(msg: String) = msg.lowercase().contains("bloqu")

    private val lockoutBody =
        """{"detail":"Ce compte est temporairement bloqué suite à plusieurs tentatives échouées.","error_code":"ACCOUNT_LOCKED","retry_after_seconds":842}"""

    @Test
    fun `429 with ACCOUNT_LOCKED shows the lockout message and the server delay`() {
        val msg = AuthErrorMapper.map(429, lockoutBody)
        assertTrue(isLockoutText(msg))
        // 842s -> 15 minutes, taken from the server, not hardcoded.
        assertTrue(msg, msg.contains("15 minute"))
    }

    @Test
    fun `lockout on a backend that still answers 401 is still recognised`() {
        val msg = AuthErrorMapper.map(401, lockoutBody)
        assertTrue(isLockoutText(msg))
    }

    @Test
    fun `wrong password never reads as a lockout`() {
        val msg = AuthErrorMapper.map(
            401,
            """{"detail":"Identifiants invalides.","error_code":"INVALID_CREDENTIALS"}"""
        )
        assertFalse(msg, isLockoutText(msg))
        assertEquals("E-mail ou mot de passe incorrect.", msg)
    }

    @Test
    fun `message text alone can never trigger the lockout message`() {
        // THE REGRESSION: the old mapper searched the body for "lock", "bloqu"
        // and "verrou", so any of these read as a locked account.
        val decoys = listOf(
            """{"detail":"Identifiants invalides. Poste verrouillé."}""",
            """{"detail":"Request blocked by upstream"}""",
            """<html><body>503 - server clock error</body></html>""",
            """{"detail":"Le jeton a expiré."}"""
        )
        for (body in decoys) {
            assertFalse(body, isLockoutText(AuthErrorMapper.map(401, body)))
            assertFalse(body, isLockoutText(AuthErrorMapper.map(500, body)))
        }
    }

    @Test
    fun `plain 429 is the ip rate limit, not an account lockout`() {
        val msg = AuthErrorMapper.map(429, """{"detail":"Rate limit exceeded"}""")
        assertFalse(msg, isLockoutText(msg))
        assertTrue(msg, msg.contains("Trop de tentatives"))
    }

    @Test
    fun `disabled account is its own message`() {
        val msg = AuthErrorMapper.map(
            403,
            """{"detail":"Ce compte est désactivé.","error_code":"ACCOUNT_DISABLED"}"""
        )
        assertFalse(msg, isLockoutText(msg))
        assertTrue(msg, msg.contains("désactivé"))
    }

    @Test
    fun `server errors and malformed bodies never read as a lockout`() {
        for (code in listOf(500, 502, 503, 504)) {
            val msg = AuthErrorMapper.map(code, null)
            assertFalse(msg, isLockoutText(msg))
        }
        assertFalse(isLockoutText(AuthErrorMapper.map(401, null)))
        assertFalse(isLockoutText(AuthErrorMapper.map(401, "")))
        assertFalse(isLockoutText(AuthErrorMapper.map(401, "not json at all")))
    }

    @Test
    fun `retry delay comes from the server, never from a hardcoded policy`() {
        assertEquals(842, AuthErrorMapper.retryAfterSecondsOf(lockoutBody))
        // Header fallback when the body omits it.
        assertEquals(
            120,
            AuthErrorMapper.retryAfterSecondsOf("""{"error_code":"ACCOUNT_LOCKED"}""", "120")
        )
        // No server value -> no invented duration.
        val msg = AuthErrorMapper.map(429, """{"error_code":"ACCOUNT_LOCKED"}""")
        assertTrue(isLockoutText(msg))
        assertFalse(msg, msg.contains("15 minute"))
    }

    @Test
    fun `delay formatting rounds up and never promises a time it was not given`() {
        assertEquals("Réessayez plus tard.", AuthErrorMapper.formatRetryDelay(null))
        assertEquals("Réessayez plus tard.", AuthErrorMapper.formatRetryDelay(0))
        assertEquals("Réessayez dans moins d'une minute.", AuthErrorMapper.formatRetryDelay(59))
        assertEquals("Réessayez dans 1 minute.", AuthErrorMapper.formatRetryDelay(60))
        assertEquals("Réessayez dans 2 minutes.", AuthErrorMapper.formatRetryDelay(61))
        assertEquals("Réessayez dans 15 minutes.", AuthErrorMapper.formatRetryDelay(900))
    }
}
