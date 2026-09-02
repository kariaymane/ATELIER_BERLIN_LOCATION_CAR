package com.example

import androidx.compose.ui.semantics.SemanticsProperties
import androidx.compose.ui.semantics.getOrNull
import androidx.compose.ui.test.ExperimentalTestApi
import androidx.compose.ui.test.junit4.StateRestorationTester
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performTextInput
import androidx.room.Room
import androidx.test.core.app.ApplicationProvider
import com.example.data.api.ApiClient
import com.example.data.api.TokenManager
import com.example.data.local.AppDatabase
import com.example.data.repository.AuthRepository
import com.example.data.repository.FleetRepository
import com.example.ui.screens.AuthScreen
import com.example.ui.viewmodel.FleetViewModel
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

/**
 * AuthScreen plaintext-password lifecycle:
 *   - a successful login clears the password field (before navigating away)
 *   - simulated process/activity recreation does NOT bring the typed password
 *     back — the field is `remember`, never `rememberSaveable`, so nothing is
 *     written to the saved-instance-state Bundle.
 *
 * The password OutlinedTextField carries testTag("auth_password_field"). Its
 * `EditableText` semantics is empty ("") when the field holds nothing and
 * non-empty (the masked bullets) when it holds a value — so emptiness is the
 * reliable, layout-independent discriminator.
 */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34])
class AuthScreenPasswordLifecycleTest {

    @get:Rule val compose = createComposeRule()

    private lateinit var server: MockWebServer
    private lateinit var db: AppDatabase
    private lateinit var vm: FleetViewModel

    private val EMAIL = "admin@ops.example.com"
    private val PASSWORD = "TypedSecret_9182"
    private val TAG = "auth_password_field"

    @Before
    fun setup() {
        val ctx = ApplicationProvider.getApplicationContext<android.content.Context>()
        server = MockWebServer().apply { start() }
        val tm = TokenManager(ctx).apply { clearAll(); saveBaseUrl(server.url("/api/v1/").toString()) }
        db = Room.inMemoryDatabaseBuilder(ctx, AppDatabase::class.java).allowMainThreadQueries().build()
        val api = ApiClient(tm)
        vm = FleetViewModel(
            authRepository = AuthRepository(api, tm),
            fleetRepository = FleetRepository(api, db, ctx),
            realtimeSyncManager = null,
            themePreferences = null,
            languagePreferences = null,
        )
    }

    @After
    fun tearDown() {
        db.close()
        try { server.shutdown() } catch (_: Throwable) {}
    }

    private fun passwordEditableText(): String =
        compose.onNodeWithTag(TAG).fetchSemanticsNode()
            .config.getOrNull(SemanticsProperties.EditableText)?.text ?: ""

    /**
     * When AuthScreen leaves composition — which is exactly what happens after
     * a successful login navigates to the dashboard, and again on logout — the
     * plaintext password must not survive. Deterministic: toggles the screen
     * out of composition and back in (logout → login) and asserts the field is
     * empty, exercising both the `onDispose { password = "" }` wipe and the
     * fresh `remember { mutableStateOf("") }` on re-entry.
     */
    @Test
    fun `password does not survive AuthScreen leaving and re-entering composition`() {
        var showAuth by mutableStateOf(true)
        compose.setContent {
            if (showAuth) AuthScreen(viewModel = vm, onLoginSuccess = {})
            else androidx.compose.material3.Text("logged in")
        }

        compose.onNodeWithTag(TAG).performTextInput(PASSWORD)
        compose.waitForIdle()
        assertTrue("sanity: password was typed", passwordEditableText().isNotEmpty())

        // login succeeded -> navigate away (AuthScreen disposed)
        showAuth = false
        compose.waitForIdle()

        // logout -> back to a brand-new AuthScreen
        showAuth = true
        compose.waitForIdle()

        assertEquals("re-entered login screen must have an empty password field",
            "", passwordEditableText())
    }

    @OptIn(ExperimentalTestApi::class)
    @Test
    fun `process recreation does not restore the typed password`() {
        val restorer = StateRestorationTester(compose)
        restorer.setContent { AuthScreen(viewModel = vm, onLoginSuccess = {}) }

        compose.onNodeWithTag(TAG).performTextInput(PASSWORD)
        compose.waitForIdle()
        assertTrue("sanity: password typed", passwordEditableText().isNotEmpty())

        restorer.emulateSavedInstanceStateRestore()
        compose.waitForIdle()

        assertEquals("typed password must NOT survive saved-instance-state restore",
            "", passwordEditableText())
    }
}
