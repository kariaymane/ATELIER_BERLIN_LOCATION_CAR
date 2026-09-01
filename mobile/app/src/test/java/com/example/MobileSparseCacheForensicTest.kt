package com.example

import androidx.room.Room
import androidx.test.core.app.ApplicationProvider
import com.example.data.api.ApiClient
import com.example.data.api.RentalDto
import com.example.data.api.SyncBootstrapResponseDto
import com.example.data.api.TokenManager
import com.example.data.api.VehicleDto
import com.example.data.fleet.BoundaryTicker
import com.example.data.fleet.FleetStatus
import com.example.data.local.AppDatabase
import com.example.data.local.VehicleEntity
import com.example.data.model.VehicleStatus
import com.example.data.repository.FleetRepository
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
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
 * Increment 5 — SPARSE-CACHE FORENSIC TEST (the exact case that blocked the
 * "100% live" verdict).
 *
 *   Backend:            Vehicle 101, reservation 101 ends in a few seconds.
 *   Initial mobile:     Vehicle 101 present, reservation 101 INTENTIONALLY
 *                       missing (page-capped incremental sync dropped it).
 *
 * That state MUST NOT be accepted as a complete temporal cache, and after a
 * full-sync the reservation interval + next boundary must exist locally and
 * the vehicle must free itself at the boundary with zero user action.
 */
@RunWith(RobolectricTestRunner::class)
class MobileSparseCacheForensicTest {

    private lateinit var db: AppDatabase
    private lateinit var repo: FleetRepository

    @Before
    fun setup() {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        db = Room.inMemoryDatabaseBuilder(context, AppDatabase::class.java)
            .allowMainThreadQueries().build()
        // Unroutable local endpoint — this suite must never reach a real server.
        val tm = TokenManager(context).apply { saveBaseUrl("http://127.0.0.1:1/api/v1/") }
        repo = FleetRepository(ApiClient(tm), db, context)
    }

    @After
    fun tearDown() = db.close()

    private fun iso(ms: Long): String =
        SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss", Locale.US).apply {
            timeZone = TimeZone.getTimeZone("UTC")
        }.format(Date(ms))

    @Test
    fun `sparse cache is not complete, full-sync repairs it, vehicle frees itself`() = runBlocking {
        // ── 1. sparse initial cache: vehicle 101, NO reservation row ──────
        db.vehicleDao().insertVehicle(
            VehicleEntity(
                "101", "Range", "Rover", "P-101", 2024, "SUV", 1000, "RENTED", 0,
                "", "", "", "", "", "", "", "", 0, 1,
            )
        )
        assertFalse("a cache that was never fully synced is NOT complete", repo.cacheCompleteFlow.first())
        assertEquals(-1L, repo.localRevision())
        assertTrue(db.reservationDao().getAllReservations().first().isEmpty())

        // with no interval row there is no boundary to schedule — the exact
        // silent-incompleteness failure mode.
        assertNull(
            FleetStatus.nextBoundaryMillis(emptyList(), emptyList(), System.currentTimeMillis())
        )

        // ── 2. authoritative full-sync ──────────────────────────────────
        val now = System.currentTimeMillis()
        val startIso = iso(now - 3_600_000)
        val endIso = iso(now + 2_000)          // ends in ~2s, no user action
        val applied = repo.applyAuthoritativeSnapshot(
            SyncBootstrapResponseDto(
                revision = now, serverTime = iso(now),
                vehicles = listOf(
                    VehicleDto(id = "101", registration = "P-101", brand = "Range", model = "Rover",
                        year = 2024, status = "RENTED", effectiveStatus = "RENTED")
                ),
                rentals = listOf(
                    RentalDto(id = "res-101", vehicleId = "101", startDatetime = startIso,
                        endDatetime = endIso, status = "ACTIVE")
                ),
                maintenance = emptyList(), notifications = emptyList(),
            )
        )
        assertTrue(applied)
        assertTrue("cache is now proven complete", repo.cacheCompleteFlow.first())

        // ── 3. the interval + the next boundary now exist locally ────────
        val resRows = db.reservationDao().getAllReservations().first()
        assertEquals(1, resRows.size)
        assertEquals("101", resRows[0].vehicleId)
        assertEquals(endIso, resRows[0].endDatetimeIso)

        val intervalRes = resRows.map {
            FleetStatus.ReservationRow(it.vehicleId, it.status, it.startDatetimeIso, it.endDatetimeIso)
        }
        val boundary = FleetStatus.nextBoundaryMillis(intervalRes, emptyList(), now)
        assertNotNull("full-sync introduced a schedulable boundary", boundary)
        assertEquals(FleetStatus.parseUtcMillis(endIso), boundary)

        // ── 4. drive the canonical vehiclesFlow pipeline over the RE-READ
        //      Room rows: RENTED before the edge, AVAILABLE at the edge,
        //      with NO API call, NO Room write, NO user action. ───────────
        val vehicles = MutableStateFlow(db.vehicleDao().getAllVehicles().first())
        val intervals = MutableStateFlow(intervalRes to emptyList<FleetStatus.MaintenanceRow>())
        val emissions = mutableListOf<VehicleStatus>()
        val job = launch {
            combine(
                vehicles, intervals,
                BoundaryTicker(nowMillis = { System.currentTimeMillis() }, delayFn = { delay(it) },
                    includeMidnight = true).ticks(intervals),
            ) { v, iv, _ ->
                FleetRepository.deriveEffectiveVehicles(v, iv.first, iv.second, System.currentTimeMillis())
            }.distinctUntilChanged().collect { list ->
                emissions.add(list.first { it.id == "101" }.status)
            }
        }

        while (emissions.isEmpty()) delay(10)
        assertEquals(VehicleStatus.EN_LOCATION, emissions.last())     // RENTED before

        val deadline = now + 5_000
        while (System.currentTimeMillis() < deadline && emissions.last() != VehicleStatus.DISPONIBLE) {
            delay(50)
        }
        assertEquals(VehicleStatus.DISPONIBLE, emissions.last())      // AVAILABLE at the boundary

        // Room row itself never mutated — the transition is pure derivation.
        assertEquals("RENTED", db.vehicleDao().getAllVehicles().first().first().status)
        job.cancel()
    }

    @Test
    fun `refreshAll forces a full bootstrap while the cache is not proven complete`() = runBlocking {
        // pre-Increment-5 style state: is_bootstrapped=true but completeness
        // flag absent (old page-capped build). refreshAll must NOT continue on
        // it — it must route to bootstrapAndReset (which will fail here with no
        // server, and that failure is the proof it took the full-sync branch,
        // not the incremental one).
        db.syncMetadataDao().setValue(
            com.example.data.local.SyncMetadataEntity(FleetRepository.META_IS_BOOTSTRAPPED, "true")
        )
        val res = repo.refreshAll()
        // It routed to bootstrapAndReset (full-sync), which fails against the
        // unroutable endpoint — proving it did NOT quietly "succeed" on the
        // possibly-sparse local cache via the incremental path.
        assertTrue("must not accept a not-proven-complete cache as synced", res.isFailure)
        assertFalse("cache still not marked complete after a failed sync", repo.cacheCompleteFlow.first())
    }
}
