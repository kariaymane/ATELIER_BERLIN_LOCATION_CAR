package com.example

import androidx.room.Room
import androidx.test.core.app.ApplicationProvider
import com.example.data.api.ApiClient
import com.example.data.api.RentalDto
import com.example.data.api.SyncBootstrapResponseDto
import com.example.data.api.TokenManager
import com.example.data.api.VehicleDto
import com.example.data.local.AppDatabase
import com.example.data.model.VehicleStatus
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

/**
 * R5 — PERMANENT GUARD: the SAME metric must have the SAME value in every
 * window that shows it.
 *
 * `Véhicules en location` on the Dashboard (`performanceMetricsFlow`) and the
 * `EN_LOCATION` tally on the Vehicles screen (`vehiclesFlow`) are the same
 * canonical metric, `RENTED`. They must agree even while the server is
 * reporting a completely different fleet — which is defect W3: the Dashboard
 * used to fall back to server counts whenever the Room pool and the API pool
 * disagreed, while the Vehicles screen kept deriving locally, so one device
 * published two answers for one metric with no diagnostic.
 *
 * `RENTED != AVAILABLE` is asserted here too: they are distinct buckets and
 * this guard must never be "satisfied" by collapsing them.
 */
@RunWith(RobolectricTestRunner::class)
class DashboardVehiclesParityTest {

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

    @Test
    fun `dashboard fleet cards equal the Vehicles screen tally even when the server disagrees`() = runBlocking {
        val now = System.currentTimeMillis()
        val hour = 3_600_000L

        // v1 is OUT right now (window contains `now`), v2 and v3 are idle.
        val snapshot = SyncBootstrapResponseDto(
            revision = 1L, serverTime = iso(now),
            vehicles = listOf(
                VehicleDto(id = "v1", registration = "AA-1", brand = "B", model = "M",
                    year = 2026, status = "AVAILABLE", effectiveStatus = "AVAILABLE"),
                VehicleDto(id = "v2", registration = "AA-2", brand = "B", model = "M",
                    year = 2026, status = "AVAILABLE", effectiveStatus = "AVAILABLE"),
                VehicleDto(id = "v3", registration = "AA-3", brand = "B", model = "M",
                    year = 2026, status = "AVAILABLE", effectiveStatus = "AVAILABLE"),
            ),
            rentals = listOf(
                RentalDto(
                    id = "r1", vehicleId = "v1", customerName = "X",
                    startDatetime = iso(now - hour), endDatetime = iso(now + hour),
                    status = "RESERVED", totalPrice = 100.0, numDays = 1,
                )
            ),
            maintenance = emptyList(),
            notifications = emptyList(),
        )
        repo.applyAuthoritativeSnapshot(snapshot)

        // The server insists on a wholly different fleet.
        val serverStatsJson = """
            {
                "today_rentals": 7, "week_rentals": 7, "month_rentals": 7, "year_rentals": 7,
                "today_revenue": 1234.0, "week_revenue": 1234.0,
                "month_revenue": 1234.0, "year_revenue": 1234.0,
                "available": 88, "rented": 12, "reserved": 5, "maintenance": 1
            }
        """.trimIndent()
        server.dispatcher = object : Dispatcher() {
            override fun dispatch(request: RecordedRequest): MockResponse =
                if (request.path?.contains("dashboard/stats") == true)
                    MockResponse().setResponseCode(200).setBody(serverStatsJson)
                else MockResponse().setResponseCode(404)
        }
        assertTrue(repo.refreshDashboard().isSuccess)

        val metrics = repo.performanceMetricsFlow.first()
        val vehicles = repo.vehiclesFlow.first()
        assertNotNull(metrics)

        val screenRented = vehicles.count { it.status == VehicleStatus.EN_LOCATION }
        val screenReady = vehicles.count { it.status == VehicleStatus.DISPONIBLE }

        assertEquals("Dashboard 'en location' must equal the Vehicles screen tally",
            screenRented, metrics!!.rentedVehicles)
        assertEquals("Dashboard 'prêts à louer' must equal the Vehicles screen tally",
            screenReady, metrics.readyVehicles)

        // ...and those are the LOCAL truth, not the server's 12 / 88.
        assertEquals(1, metrics.rentedVehicles)
        assertEquals(2, metrics.readyVehicles)

        // RENTED and AVAILABLE remain DISTINCT metrics — never merged.
        assertTrue("RENTED must not be conflated with AVAILABLE",
            metrics.rentedVehicles != metrics.readyVehicles)

        // Revenue stays server-authoritative through all of the above.
        assertEquals(1234.0, metrics.todayRevenue, 0.001)

        // The four buckets partition the local pool exactly.
        assertEquals(
            vehicles.size,
            metrics.readyVehicles + metrics.rentedVehicles +
                metrics.reservedVehicles + metrics.maintenanceVehicles,
        )
    }
}
