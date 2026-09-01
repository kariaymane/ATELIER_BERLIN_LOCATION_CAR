package com.example

import android.content.Context
import android.util.Base64
import androidx.test.core.app.ApplicationProvider
import com.example.data.api.JwtUtils
import com.example.data.api.TokenManager
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner

/**
 * Regression guard for the "login once, stay logged in until logout" fix.
 *
 * Covers the two novel pieces of logic the fix introduces:
 *   - JwtUtils local-expiry inspection (used to decide whether a cached session
 *     may unlock the app while the server is unreachable), and
 *   - TokenManager.clearSession() clearing credentials WITHOUT wiping the
 *     operator-configured API base URL.
 *
 * The full offline session-restore flow (AuthRepository.validateAndRestoreSession
 * entering with a cached session on a 5xx/timeout and clearing it on an explicit
 * 401) is exercised by instrumentation tests against MockWebServer — not
 * reproducible in this plain-JVM unit environment.
 */
@RunWith(RobolectricTestRunner::class)
class SessionPersistenceTest {

    private lateinit var context: Context
    private lateinit var tokenManager: TokenManager

    @Before
    fun setup() {
        context = ApplicationProvider.getApplicationContext()
        tokenManager = TokenManager(context)
        tokenManager.clearAll()
    }

    private fun jwtWithExp(epochSeconds: Long): String {
        val header = Base64.encodeToString(
            """{"alg":"HS256","typ":"JWT"}""".toByteArray(),
            Base64.URL_SAFE or Base64.NO_PADDING or Base64.NO_WRAP
        )
        val payload = Base64.encodeToString(
            """{"sub":"u1","exp":$epochSeconds}""".toByteArray(),
            Base64.URL_SAFE or Base64.NO_PADDING or Base64.NO_WRAP
        )
        return "$header.$payload.signature"
    }

    @Test
    fun futureTokenIsProbablyValidAndNotExpired() {
        val token = jwtWithExp(System.currentTimeMillis() / 1000L + 3600)
        assertTrue(JwtUtils.isProbablyValid(token))
        assertFalse(JwtUtils.isDefinitelyExpired(token))
    }

    @Test
    fun pastTokenIsDefinitelyExpired() {
        val token = jwtWithExp(System.currentTimeMillis() / 1000L - 3600)
        assertTrue(JwtUtils.isDefinitelyExpired(token))
        assertFalse(JwtUtils.isProbablyValid(token))
    }

    @Test
    fun unreadableTokenIsTreatedAsUnknownNotExpired() {
        // Opaque / non-JWT tokens must NOT be assumed expired — the server
        // stays the authority for those.
        assertFalse(JwtUtils.isDefinitelyExpired("opaque-token"))
        assertFalse(JwtUtils.isDefinitelyExpired(null))
        assertNull(JwtUtils.expiresAtEpochSeconds("not.a.jwt.at.all"))
    }

    @Test
    fun clearSessionKeepsConfiguredBaseUrlButDropsCredentials() {
        tokenManager.saveBaseUrl("https://ops.example.com/api/v1")
        tokenManager.saveToken("access-123")
        tokenManager.saveRefreshToken("refresh-123")
        tokenManager.saveUser("u1", "admin@example.com", "Admin", "ADMIN")

        tokenManager.clearSession()

        assertNull(tokenManager.getToken())
        assertNull(tokenManager.getRefreshToken())
        assertNull(tokenManager.getStoredUserEmail())
        assertEquals("https://ops.example.com/api/v1/", tokenManager.getBaseUrl())
    }

    @Test
    fun clearAllAlsoResetsBaseUrl() {
        tokenManager.saveBaseUrl("https://ops.example.com/api/v1")
        tokenManager.saveToken("access-123")

        tokenManager.clearAll()

        assertNull(tokenManager.getToken())
        assertEquals(TokenManager.DEFAULT_BASE_URL, tokenManager.getBaseUrl())
    }
}
