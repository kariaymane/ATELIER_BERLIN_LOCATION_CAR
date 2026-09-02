package com.example

import android.content.Context
import androidx.room.Room
import androidx.test.core.app.ApplicationProvider
import com.example.data.api.ApiClient
import com.example.data.api.TokenManager
import com.example.data.local.AppDatabase
import com.example.data.repository.AuthRepository
import com.example.data.repository.FleetRepository
import kotlinx.coroutines.runBlocking
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.After
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import java.io.File

/**
 * FORENSIC: the user's plaintext login password must never come to rest in any
 * recoverable location — SharedPreferences, Room, files, or a long-lived object
 * field. This drives a REAL login through the OkHttp/Retrofit stack against a
 * MockWebServer and then sweeps every persistence surface for the secret.
 */
@RunWith(RobolectricTestRunner::class)
class MobilePasswordForensicTest {

    private val SECRET = "Sup3rSecret!Passw0rd_forensic"

    private lateinit var context: Context
    private lateinit var server: MockWebServer
    private lateinit var tokenManager: TokenManager
    private lateinit var db: AppDatabase
    private lateinit var auth: AuthRepository
    private lateinit var fleet: FleetRepository

    @Before
    fun setup() {
        context = ApplicationProvider.getApplicationContext()
        server = MockWebServer().apply { start() }
        tokenManager = TokenManager(context).apply { clearAll() }
        tokenManager.saveBaseUrl(server.url("/api/v1/").toString())
        db = Room.inMemoryDatabaseBuilder(context, AppDatabase::class.java)
            .allowMainThreadQueries().build()
        val api = ApiClient(tokenManager)
        auth = AuthRepository(api, tokenManager)
        fleet = FleetRepository(api, db, context)
    }

    @After
    fun tearDown() {
        db.close()
        try { server.shutdown() } catch (_: Throwable) {}
    }

    private fun doLogin() = runBlocking {
        server.enqueue(
            MockResponse().setResponseCode(200).setBody(
                """{"access_token":"header.payload.sig","refresh_token":"r.e.f",
                    "token_type":"bearer","expires_in":900,
                    "user_id":"u-1","role":"ADMIN","full_name":"Ops Admin"}"""
            )
        )
        val r = auth.login("admin@ops.example.com", SECRET)
        assertTrue("login should succeed against the mock", r.isSuccess)
    }

    // ── SharedPreferences (all app pref files) ─────────────────────────────
    @Test
    fun `no SharedPreferences value or key contains the password after login`() {
        doLogin()
        val prefsDir = File(context.applicationInfo.dataDir, "shared_prefs")
        val files = prefsDir.listFiles()?.filter { it.name.endsWith(".xml") } ?: emptyList()
        assertTrue("expected at least the auth prefs file to exist", files.isNotEmpty())
        for (f in files) {
            val xml = f.readText()
            assertFalse("${f.name} must not contain the plaintext password", xml.contains(SECRET))
            assertFalse("${f.name} must not contain a 'password' key",
                Regex("name=\"[^\"]*(?i:password|passwd|pwd)[^\"]*\"").containsMatchIn(xml))
        }
        // the token WAS persisted — that is the intended session mechanism.
        assertTrue("access token must be persisted", tokenManager.getToken()?.isNotBlank() == true)
        assertTrue("refresh token must be persisted", tokenManager.getRefreshToken()?.isNotBlank() == true)
    }

    // ── Room / SQLite ─────────────────────────────────────────────────────
    @Test
    fun `Room schema has no credential column and holds no password`() = runBlocking {
        doLogin()
        // a full snapshot apply, to populate sync_metadata + business tables
        fleet.applyAuthoritativeSnapshot(
            com.example.data.api.SyncBootstrapResponseDto(
                revision = 1, serverTime = "2026-09-02T00:00:00",
                vehicles = emptyList(), rentals = emptyList(),
                maintenance = emptyList(), notifications = emptyList(),
            )
        )
        val cur = db.openHelper.readableDatabase.query(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
        val tables = mutableListOf<String>()
        cur.use { while (it.moveToNext()) tables.add(it.getString(0)) }
        for (t in tables) {
            if (t.startsWith("sqlite_") || t == "android_metadata" || t == "room_master_table") continue
            val info = db.openHelper.readableDatabase.query("PRAGMA table_info(`$t`)")
            info.use {
                while (it.moveToNext()) {
                    val col = it.getString(it.getColumnIndexOrThrow("name")).lowercase()
                    assertFalse("table $t exposes a credential column '$col'",
                        col.contains("password") || col.contains("passwd") || col == "pwd" ||
                        col.contains("secret") || col.contains("credential"))
                }
            }
            // scan every text value in the table for the secret
            val rows = db.openHelper.readableDatabase.query("SELECT * FROM `$t`")
            rows.use {
                while (it.moveToNext()) {
                    for (c in 0 until it.columnCount) {
                        val v = runCatching { it.getString(c) }.getOrNull() ?: continue
                        assertFalse("table $t row value contains the password", v.contains(SECRET))
                    }
                }
            }
        }
    }

    // ── no long-lived object retains the plaintext password ────────────────
    @Test
    fun `AuthRepository and TokenManager retain no field equal to the password`() {
        doLogin()
        for (target in listOf<Any>(auth, tokenManager)) {
            var c: Class<*>? = target.javaClass
            while (c != null && c != Any::class.java) {
                for (field in c.declaredFields) {
                    field.isAccessible = true
                    val value = runCatching { field.get(target) }.getOrNull()
                    val text = when (value) {
                        is String -> value
                        is CharArray -> String(value)
                        else -> value?.toString()
                    }
                    if (text != null) {
                        assertFalse(
                            "${target.javaClass.simpleName}.${field.name} still holds the password",
                            text.contains(SECRET)
                        )
                    }
                }
                c = c.superclass
            }
        }
    }

    // ── files / cache dir sweep ───────────────────────────────────────────
    @Test
    fun `no file under the app data dir contains the password`() {
        doLogin()
        val root = File(context.applicationInfo.dataDir)
        val hits = root.walkTopDown()
            .filter { it.isFile && it.length() in 1..2_000_000 }
            .filter { f ->
                runCatching { f.readBytes().toString(Charsets.ISO_8859_1).contains(SECRET) }
                    .getOrDefault(false)
            }
            .map { it.relativeTo(root).path }
            .toList()
        assertTrue("password found in files: $hits", hits.isEmpty())
    }
}
