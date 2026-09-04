package com.example

import androidx.room.Room
import androidx.test.core.app.ApplicationProvider
import com.example.data.api.ApiClient
import com.example.data.api.RentalDto
import com.example.data.api.SyncBootstrapResponseDto
import com.example.data.api.TokenManager
import com.example.data.api.VehicleDto
import com.example.data.local.AppDatabase
import com.example.data.model.ServerReachability
import com.example.data.model.SyncStatusState
import com.example.data.repository.FleetRepository
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import okhttp3.mockwebserver.Dispatcher
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okhttp3.mockwebserver.RecordedRequest
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.TimeZone

/**
 * MOBILE ERROR UX + ROOM CACHE FALLBACK (the contract behind fix #3).
 *
 * When a sync fails because the server is unreachable OR because the server is
 * reachable but its database is down, the app must:
 *   - keep the previous complete Room snapshot exactly as-is (no wipe, no
 *     fabrication, no silent overwrite)
 *   - report a NON-fatal, correctly-classified status
 *       * DB down     -> SERVER_DB_UNAVAILABLE
 *       * unreachable  -> SYNC_ERROR + reachability UNREACHABLE
 *   - recover automatically to SYNCED once the backend answers again
 * With an EMPTY cache the failure is still a failure — nothing is invented.
 */
@RunWith(RobolectricTestRunner::class)
class MobileOfflineCacheFallbackTest {

    private lateinit var server: MockWebServer
    private lateinit var rawDb: AppDatabase
    private lateinit var repo: FleetRepository

    @Before
    fun setup() {
        val ctx = ApplicationProvider.getApplicationContext<android.content.Context>()
        server = MockWebServer().apply { start() }
        rawDb = Room.inMemoryDatabaseBuilder(ctx, AppDatabase::class.java)
            .allowMainThreadQueries().build()
        val tm = TokenManager(ctx)
        tm.clearAll()
        tm.saveBaseUrl(server.url("/api/v1/").toString())
        repo = FleetRepository(ApiClient(tm), rawDb, ctx)
    }

    @After
    fun tearDown() {
        rawDb.close()
        try { server.shutdown() } catch (_: Throwable) {}
    }

    private fun iso(ms: Long): String =
        SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ssXXX", Locale.US).apply {
            timeZone = TimeZone.getTimeZone("UTC")
        }.format(Date(ms))

    private fun goodSnapshot(rev: Long): SyncBootstrapResponseDto {
        val now = System.currentTimeMillis()
        return SyncBootstrapResponseDto(
            revision = rev, serverTime = iso(now),
            vehicles = listOf(
                VehicleDto(id = "v1", registration = "AB-123", brand = "Range", model = "Rover",
                    year = 2024, status = "AVAILABLE", effectiveStatus = "AVAILABLE")
            ),
            rentals = listOf(
                RentalDto(id = "r1", vehicleId = "v1",
                    startDatetime = iso(now + 86_400_000), endDatetime = iso(now + 172_800_000),
                    status = "RESERVED")
            ),
            maintenance = emptyList(), notifications = emptyList(),
        )
    }

    private fun dispatch(handler: (RecordedRequest) -> MockResponse) {
        server.dispatcher = object : Dispatcher() {
            override fun dispatch(request: RecordedRequest) = handler(request)
        }
    }

    private suspend fun seedCompleteCache() {
        assertTrue(repo.applyAuthoritativeSnapshot(goodSnapshot(rev = 1000L)))
        assertTrue(repo.cacheCompleteFlow.first())
        assertEquals(1, rawDb.vehicleDao().getAllVehicles().first().size)
    }

    // ── server reachable, database down (readiness/bootstrap 503) ───────────
    @Test
    fun `db-down keeps the cached snapshot and reports SERVER_DB_UNAVAILABLE`() = runBlocking {
        seedCompleteCache()
        dispatch { req ->
            when {
                req.path?.contains("/sync/bootstrap") == true -> MockResponse().setResponseCode(503)
                    .setBody("""{"detail":"db down"}""")
                req.path?.startsWith("/health/ready") == true -> MockResponse().setResponseCode(503)
                    .setBody("""{"status":"not_ready","database":"unavailable"}""")
                else -> MockResponse().setResponseCode(503)
            }
        }

        val result = repo.refreshAll()

        assertTrue("sync must report failure, not fake success", result.isFailure)
        // cache untouched
        assertEquals(1, rawDb.vehicleDao().getAllVehicles().first().size)
        assertEquals("v1", rawDb.vehicleDao().getAllVehicles().first().first().id)
        assertTrue(repo.cacheCompleteFlow.first())
        // classified, non-fatal
        val s = repo.syncStatusFlow.value
        assertEquals(SyncStatusState.SERVER_DB_UNAVAILABLE, s.state)
        assertTrue(s.isServerDatabaseDown)
        assertTrue(s.isShowingStaleData)
    }

    // ── server totally unreachable ─────────────────────────────────────────
    @Test
    fun `unreachable server keeps the cache and reports SYNC_ERROR + UNREACHABLE`() = runBlocking {
        seedCompleteCache()
        server.shutdown()

        val result = repo.refreshAll()

        assertTrue(result.isFailure)
        assertEquals(1, rawDb.vehicleDao().getAllVehicles().first().size)
        val s = repo.syncStatusFlow.value
        assertEquals(SyncStatusState.SYNC_ERROR, s.state)
        assertEquals(ServerReachability.UNREACHABLE, s.reachability)
        assertFalse(s.isServerDatabaseDown)
        assertTrue(s.isShowingStaleData)
    }

    // ── automatic recovery once the backend answers again ──────────────────
    @Test
    fun `sync recovers to SYNCED when the backend comes back`() = runBlocking {
        seedCompleteCache()

        // first attempt: DB down
        dispatch { req ->
            if (req.path?.contains("/sync/bootstrap") == true) MockResponse().setResponseCode(503)
            else MockResponse().setResponseCode(503)
        }
        assertTrue(repo.refreshAll().isFailure)
        assertEquals(SyncStatusState.SERVER_DB_UNAVAILABLE, repo.syncStatusFlow.value.state)

        // backend recovers
        dispatch { req ->
            when {
                req.path?.contains("/sync/bootstrap") == true -> MockResponse().setResponseCode(200)
                    .setBody(SNAPSHOT_JSON)
                req.path?.contains("/dashboard/stats") == true -> MockResponse().setResponseCode(200)
                    .setBody("{}")
                req.path?.startsWith("/health/ready") == true -> MockResponse().setResponseCode(200)
                    .setBody("""{"status":"ready","database":"connected"}""")
                else -> MockResponse().setResponseCode(200).setBody("{}")
            }
        }

        val recovered = repo.refreshAll()
        assertTrue(recovered.isSuccess)
        assertEquals(SyncStatusState.SYNCED, repo.syncStatusFlow.value.state)
        assertEquals(ServerReachability.ONLINE, repo.syncStatusFlow.value.reachability)
        assertEquals(1, rawDb.vehicleDao().getAllVehicles().first().size)
    }

    // ── empty cache: a failure is still a failure, nothing invented ────────
    @Test
    fun `empty cache plus db-down fails cleanly without fabricating data`() = runBlocking {
        // no seed — fresh install
        assertFalse(repo.cacheCompleteFlow.first())
        dispatch { MockResponse().setResponseCode(503).setBody("""{"detail":"db down"}""") }

        val result = repo.refreshAll()

        assertTrue(result.isFailure)
        assertTrue(rawDb.vehicleDao().getAllVehicles().first().isEmpty())
        assertFalse(repo.cacheCompleteFlow.first())
    }

    companion object {
        // A minimal valid /sync/bootstrap body (revision newer than the seeded 1000).
        private val SNAPSHOT_JSON = """
            {"sync_version":1,"revision":2000,"server_time":"2026-09-01T00:00:00",
             "server_id":"car-rental-server-v1","api_version":"1.0.0",
             "vehicles":[{"id":"v1","registration":"AB-123","brand":"Range","model":"Rover",
                          "year":2024,"status":"AVAILABLE","effective_status":"AVAILABLE"}],
             "rentals":[],"maintenance":[],"notifications":[]}
        """.trimIndent()
    }
}
