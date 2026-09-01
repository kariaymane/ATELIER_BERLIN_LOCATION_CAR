package com.example

import androidx.room.Room
import androidx.test.core.app.ApplicationProvider
import com.example.data.api.ApiClient
import com.example.data.api.TokenManager
import com.example.data.local.AppDatabase
import com.example.data.model.ServerReachability
import com.example.data.repository.FleetRepository
import kotlinx.coroutines.runBlocking
import okhttp3.mockwebserver.Dispatcher
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okhttp3.mockwebserver.RecordedRequest
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner

/**
 * `FleetRepository.probeServer()` must tell three states apart, because the UI
 * and the sync policy react differently to each:
 *
 *   ONLINE        — server up, database answered `SELECT 1`
 *   DATABASE_DOWN — server up, readiness returned 503 (the exact production
 *                   outage: `/health` green, every DB call 500)
 *   UNREACHABLE   — DNS / connect / timeout
 *
 * and it must never throw.
 */
@RunWith(RobolectricTestRunner::class)
class MobileServerReadinessProbeTest {

    private lateinit var server: MockWebServer
    private lateinit var db: AppDatabase
    private lateinit var repo: FleetRepository

    @Before
    fun setup() {
        val ctx = ApplicationProvider.getApplicationContext<android.content.Context>()
        server = MockWebServer().apply { start() }
        db = Room.inMemoryDatabaseBuilder(ctx, AppDatabase::class.java)
            .allowMainThreadQueries().build()
        val tm = TokenManager(ctx)
        tm.clearAll()
        tm.saveBaseUrl(server.url("/api/v1/").toString())
        repo = FleetRepository(ApiClient(tm), db, ctx)
    }

    @After
    fun tearDown() {
        db.close()
        try { server.shutdown() } catch (_: Throwable) {}
    }

    private fun dispatch(handler: (RecordedRequest) -> MockResponse) {
        server.dispatcher = object : Dispatcher() {
            override fun dispatch(request: RecordedRequest): MockResponse = handler(request)
        }
    }

    @Test
    fun `readiness 200 ready maps to ONLINE`() = runBlocking {
        dispatch { req ->
            if (req.path?.startsWith("/health/ready") == true)
                MockResponse().setResponseCode(200)
                    .setBody("""{"status":"ready","database":"connected"}""")
            else MockResponse().setResponseCode(404)
        }
        assertEquals(ServerReachability.ONLINE, repo.probeServer())
    }

    @Test
    fun `readiness 503 maps to DATABASE_DOWN`() = runBlocking {
        dispatch { req ->
            if (req.path?.startsWith("/health/ready") == true)
                MockResponse().setResponseCode(503)
                    .setBody("""{"status":"not_ready","database":"unavailable","error_category":"OperationalError"}""")
            else MockResponse().setResponseCode(404)
        }
        assertEquals(ServerReachability.DATABASE_DOWN, repo.probeServer())
    }

    @Test
    fun `server shut down maps to UNREACHABLE, never throws`() = runBlocking {
        server.shutdown()
        assertEquals(ServerReachability.UNREACHABLE, repo.probeServer())
    }

    @Test
    fun `older backend without ready endpoint falls back to liveness = ONLINE`() = runBlocking {
        dispatch { req ->
            when {
                req.path?.startsWith("/health/ready") == true -> MockResponse().setResponseCode(404)
                req.path == "/health" -> MockResponse().setResponseCode(200)
                    .setBody("""{"status":"alive","version":"1.0.0"}""")
                else -> MockResponse().setResponseCode(404)
            }
        }
        assertEquals(ServerReachability.ONLINE, repo.probeServer())
    }

    @Test
    fun `older backend, ready 404 and liveness also down = UNREACHABLE`() = runBlocking {
        dispatch { MockResponse().setResponseCode(404) }
        assertEquals(ServerReachability.UNREACHABLE, repo.probeServer())
    }
}
