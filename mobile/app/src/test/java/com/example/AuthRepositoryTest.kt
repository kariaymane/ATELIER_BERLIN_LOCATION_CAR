package com.example

import android.content.Context
import androidx.test.core.app.ApplicationProvider
import com.example.data.api.TokenManager
import com.example.data.model.UserSession
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner

@RunWith(RobolectricTestRunner::class)
class AuthRepositoryTest {

    private lateinit var context: Context
    private lateinit var tokenManager: TokenManager

    @Before
    fun setup() {
        context = ApplicationProvider.getApplicationContext()
        tokenManager = TokenManager(context)
        tokenManager.clearAll()
    }

    @Test
    fun testTokenManagerSaveAndClear() {
        assertNull(tokenManager.getToken())

        tokenManager.saveToken("test_token_12345")
        assertEquals("test_token_12345", tokenManager.getToken())

        tokenManager.saveUser("u1", "admin@carrental.com", "Admin Test", "ADMIN")
        assertEquals("admin@carrental.com", tokenManager.getUserEmail())
        assertEquals("Admin Test", tokenManager.getUserName())
        assertEquals("ADMIN", tokenManager.getUserRole())

        tokenManager.clearToken()
        assertNull(tokenManager.getToken())
    }

    @Test
    fun testBaseUrlConfiguration() {
        assertEquals(TokenManager.DEFAULT_BASE_URL, tokenManager.getBaseUrl())

        tokenManager.saveBaseUrl("http://192.168.1.50:8000/api/v1")
        assertEquals("http://192.168.1.50:8000/api/v1/", tokenManager.getBaseUrl())
        assertEquals("http://192.168.1.50:8000", tokenManager.getRootUrl())
    }

    @Test
    fun testUserSessionModel() {
        val session = UserSession(
            id = "user_123",
            email = "jean.dupont@softexecutive.com",
            name = "Jean Dupont",
            role = "MANAGER",
            token = "jwt_token_xyz",
            initials = "JD"
        )

        assertEquals("user_123", session.id)
        assertEquals("Jean Dupont", session.name)
        assertEquals("JD", session.initials)
        assertEquals("MANAGER", session.role)
    }
}
