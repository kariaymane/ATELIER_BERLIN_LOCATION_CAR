package com.example

import androidx.room.Room
import androidx.test.core.app.ApplicationProvider
import com.example.data.api.ApiClient
import com.example.data.api.RentalDto
import com.example.data.api.SyncBootstrapResponseDto
import com.example.data.api.TokenManager
import com.example.data.api.VehicleDto
import com.example.data.local.AppDatabase
import com.example.data.repository.FleetRepository
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import okhttp3.mockwebserver.Dispatcher
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okhttp3.mockwebserver.RecordedRequest
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.TimeZone

@RunWith(RobolectricTestRunner::class)
class MobileLiveAuthorityTest {

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
        SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss", Locale.US).apply {
            timeZone = TimeZone.getTimeZone("UTC")
        }.format(Date(ms))

    @Test
    fun `performanceMetricsFlow prioritizes live server API over local Room cache and resists Room overwrite`() = runBlocking {
        val now = System.currentTimeMillis()

        // 1. Seed Room with initial snapshot (1 vehicle)
        val snapshot = SyncBootstrapResponseDto(
            revision = 100L, serverTime = iso(now),
            vehicles = listOf(
                VehicleDto(id = "v1", registration = "LOC-1", brand = "LocalBrand", model = "LocalModel",
                    year = 2024, status = "AVAILABLE", effectiveStatus = "AVAILABLE")
            ),
            rentals = emptyList(),
            maintenance = emptyList(),
            notifications = emptyList()
        )
        repo.applyAuthoritativeSnapshot(snapshot)

        // Before server stats: local metrics computed from Room
        val initialLocal = repo.performanceMetricsFlow.first()
        assertNotNull(initialLocal)
        assertEquals(0, initialLocal!!.todayBookings)
        assertEquals(1, initialLocal.readyVehicles)

        // 2. Mock /api/v1/dashboard/stats returning live server stats
        val serverStatsJson = """
            {
                "today_rentals": 42,
                "week_rentals": 100,
                "month_rentals": 300,
                "year_rentals": 1200,
                "today_revenue": 9999.0,
                "week_revenue": 25000.0,
                "month_revenue": 80000.0,
                "year_revenue": 500000.0,
                "available": 88,
                "rented": 12,
                "reserved": 5,
                "maintenance": 1
            }
        """.trimIndent()

        server.dispatcher = object : Dispatcher() {
            override fun dispatch(request: RecordedRequest): MockResponse {
                if (request.path?.contains("dashboard/stats") == true) {
                    return MockResponse().setResponseCode(200).setBody(serverStatsJson)
                }
                return MockResponse().setResponseCode(404)
            }
        }

        // 3. Fetch server dashboard stats
        val refreshRes = repo.refreshDashboard()
        assertTrue(refreshRes.isSuccess)

        // 4. Assert performanceMetricsFlow now reflects authoritative live server data
        val liveMetrics = repo.performanceMetricsFlow.first()
        assertNotNull(liveMetrics)
        assertEquals(42, liveMetrics!!.todayBookings)
        assertEquals(9999.0, liveMetrics.todayRevenue, 0.001)
        assertEquals(88, liveMetrics.readyVehicles)
        assertEquals(12, liveMetrics.rentedVehicles)

        // 5. Simulate subsequent Room emission (e.g. background sync writes another row to Room)
        val secondSnapshot = SyncBootstrapResponseDto(
            revision = 101L, serverTime = iso(now),
            vehicles = listOf(
                VehicleDto(id = "v1", registration = "LOC-1", brand = "LocalBrand", model = "LocalModel",
                    year = 2024, status = "AVAILABLE", effectiveStatus = "AVAILABLE"),
                VehicleDto(id = "v2", registration = "LOC-2", brand = "LocalBrand2", model = "LocalModel2",
                    year = 2024, status = "AVAILABLE", effectiveStatus = "AVAILABLE")
            ),
            rentals = emptyList(),
            maintenance = emptyList(),
            notifications = emptyList()
        )
        repo.applyAuthoritativeSnapshot(secondSnapshot)

        // 6. Assert live server data is STILL authoritative and NOT overwritten by Room!
        val metricsAfterRoomCommit = repo.performanceMetricsFlow.first()
        assertNotNull(metricsAfterRoomCommit)
        assertEquals(42, metricsAfterRoomCommit!!.todayBookings)
        assertEquals(9999.0, metricsAfterRoomCommit.todayRevenue, 0.001)
        assertEquals(88, metricsAfterRoomCommit.readyVehicles)
        assertEquals(12, metricsAfterRoomCommit.rentedVehicles)
    }
}
