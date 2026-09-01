package com.example

import android.content.Context
import android.util.Base64
import androidx.test.core.app.ApplicationProvider
import com.example.data.api.ApiClient
import com.example.data.api.TokenManager
import com.example.data.repository.AuthRepository
import kotlinx.coroutines.runBlocking
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner

/**
 * End-to-end regression guard for `AuthRepository.validateAndRestoreSession()`,
 * the cold-start session-restore flow behind the "log in once, stay logged in
 * until logout" fix.
 *
 * Unlike [SessionPersistenceTest] (which unit-tests the two helper pieces —
 * JwtUtils and TokenManager.clearSession), this drives the *whole* flow through
 * the real OkHttp / Retrofit stack against a [MockWebServer], asserting the one
 * property that regressed in production:
 *
 *   a transient server condition (timeout / 5xx / unreachable) must NEVER wipe a
 *   still-valid stored session, while an explicit 401/403 always must.
 */
@RunWith(RobolectricTestRunner::class)
class SessionRestoreFlowTest {

    private lateinit var context: Context
    private lateinit var server: MockWebServer
    private lateinit var tokenManager: TokenManager
    private lateinit var apiClient: ApiClient
    private lateinit var repo: AuthRepository

    private val validAccess = jwtWithExp(nowSeconds() + 3600)
    private val validRefresh = jwtWithExp(nowSeconds() + 7 * 24 * 3600)

    @Before
    fun setup() {
        context = ApplicationProvider.getApplicationContext()
        server = MockWebServer()
        server.start()

        tokenManager = TokenManager(context)
        tokenManager.clearAll()
        // Saved AFTER construction so TokenManager.init()'s localhost/http reset
        // does not fire — this mirrors an operator-configured server URL.
        tokenManager.saveBaseUrl(server.url("/api/v1/").toString())

        apiClient = ApiClient(tokenManager)
        repo = AuthRepository(apiClient, tokenManager)
    }

    @After
    fun tearDown() {
        try {
            server.shutdown()
        } catch (_: Throwable) {
        }
    }

    /** Seed a fully-populated, locally-valid stored session. */
    private fun seedStoredSession(
        access: String = validAccess,
        refresh: String? = validRefresh,
    ) {
        tokenManager.saveToken(access)
        refresh?.let { tokenManager.saveRefreshToken(it) }
        tokenManager.saveUser(
            id = "u-1",
            email = "admin@ops.example.com",
            name = "Ops Admin",
            role = "ADMIN",
        )
    }

    private fun configuredBaseUrl() = tokenManager.getBaseUrl()

    // ── refresh-token path ────────────────────────────────────────────────

    @Test
    fun transient5xxOnRefreshKeepsCachedSession() = runBlocking {
        seedStoredSession()
        server.enqueue(MockResponse().setResponseCode(503).setBody("upstream cold start"))

        repo.validateAndRestoreSession()

        assertNotNull("session must survive a 503 on refresh", repo.currentUserSession.value)
        assertEquals("u-1", repo.currentUserSession.value?.id)
        assertEquals(validAccess, tokenManager.getToken())
        assertEquals(validRefresh, tokenManager.getRefreshToken())
        assertTrue(configuredBaseUrl().contains(server.hostName))
    }

    @Test
    fun serverUnreachableOnRefreshKeepsCachedSession() = runBlocking {
        seedStoredSession()
        server.shutdown() // connection refused, not a clean HTTP status

        repo.validateAndRestoreSession()

        assertNotNull("session must survive an unreachable server", repo.currentUserSession.value)
        assertEquals(validAccess, tokenManager.getToken())
        assertEquals(validRefresh, tokenManager.getRefreshToken())
    }

    @Test
    fun explicit401OnRefreshClearsSessionButKeepsBaseUrl() = runBlocking {
        seedStoredSession()
        val savedUrl = configuredBaseUrl()
        server.enqueue(MockResponse().setResponseCode(401).setBody("""{"detail":"token revoked"}"""))

        repo.validateAndRestoreSession()

        assertNull("explicit 401 must kill the session", repo.currentUserSession.value)
        assertNull(tokenManager.getToken())
        assertNull(tokenManager.getRefreshToken())
        assertNull(tokenManager.getStoredUserEmail())
        assertEquals("operator base URL must be retained", savedUrl, configuredBaseUrl())
    }

    @Test
    fun successfulRefreshRotatesTokensAndRestoresSession() = runBlocking {
        seedStoredSession()
        val newAccess = jwtWithExp(nowSeconds() + 3600)
        val newRefresh = jwtWithExp(nowSeconds() + 7 * 24 * 3600)
        server.enqueue(
            MockResponse().setResponseCode(200).setBody(
                """{"access_token":"$newAccess","refresh_token":"$newRefresh","token_type":"bearer"}"""
            )
        )

        repo.validateAndRestoreSession()

        assertNotNull(repo.currentUserSession.value)
        assertEquals(newAccess, repo.currentUserSession.value?.token)
        assertEquals(newAccess, tokenManager.getToken())
        assertEquals(newRefresh, tokenManager.getRefreshToken())
    }

    @Test
    fun provablyExpiredTokensWithUnreachableServerClearSession() = runBlocking {
        val deadAccess = jwtWithExp(nowSeconds() - 3600)
        val deadRefresh = jwtWithExp(nowSeconds() - 60)
        seedStoredSession(access = deadAccess, refresh = deadRefresh)
        server.shutdown()

        repo.validateAndRestoreSession()

        assertNull("no offline fallback when both tokens are provably expired", repo.currentUserSession.value)
        assertNull(tokenManager.getToken())
    }

    @Test
    fun noStoredTokensClearsAndStaysLoggedOut() = runBlocking {
        // identity present but no tokens at all -> nothing to restore
        tokenManager.saveUser("u-1", "admin@ops.example.com", "Ops Admin", "ADMIN")

        repo.validateAndRestoreSession()

        assertNull(repo.currentUserSession.value)
        assertNull(tokenManager.getStoredUserEmail())
    }

    // ── probe path (access token only, no refresh token) ──────────────────

    @Test
    fun probe200RestoresSessionWhenNoRefreshToken() = runBlocking {
        seedStoredSession(refresh = null)
        server.enqueue(MockResponse().setResponseCode(200).setBody("{}"))

        repo.validateAndRestoreSession()

        assertNotNull(repo.currentUserSession.value)
        assertEquals(validAccess, tokenManager.getToken())
    }

    @Test
    fun probe401ClearsSessionWhenNoRefreshToken() = runBlocking {
        seedStoredSession(refresh = null)

        server.enqueue(MockResponse().setResponseCode(401))

        repo.validateAndRestoreSession()

        assertNull(repo.currentUserSession.value)
        assertNull(tokenManager.getToken())
    }

    @Test
    fun probe503WithNonExpiredTokenKeepsCachedSessionWhenNoRefreshToken() = runBlocking {
        seedStoredSession(refresh = null)
        server.enqueue(MockResponse().setResponseCode(503))

        repo.validateAndRestoreSession()

        assertNotNull("a 503 on the probe must not wipe a non-expired session", repo.currentUserSession.value)
        assertEquals(validAccess, tokenManager.getToken())
    }

    companion object {
        private fun nowSeconds() = System.currentTimeMillis() / 1000L

        private fun jwtWithExp(epochSeconds: Long): String {
            fun b64(s: String) = Base64.encodeToString(
                s.toByteArray(), Base64.URL_SAFE or Base64.NO_PADDING or Base64.NO_WRAP
            )
            val header = b64("""{"alg":"HS256","typ":"JWT"}""")
            val payload = b64("""{"sub":"u-1","exp":$epochSeconds}""")
            return "$header.$payload.signature"
        }
    }
}
