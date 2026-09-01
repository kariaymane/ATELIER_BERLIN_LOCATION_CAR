package com.example

import androidx.room.Room
import androidx.test.core.app.ApplicationProvider
import com.example.data.api.ApiClient
import com.example.data.api.MaintenanceDto
import com.example.data.api.RentalDto
import com.example.data.api.SyncBootstrapResponseDto
import com.example.data.api.TokenManager
import com.example.data.api.VehicleDto
import com.example.data.fleet.FleetStatus
import com.example.data.local.AppDatabase
import com.example.data.repository.FleetRepository
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner

/**
 * Increment 5 — TEMPORAL-CACHE COMPLETENESS + REVISION SAFETY.
 *
 * The blocker before this increment: the mobile incremental refresh fetched
 * only page 1 (100 rows) of reservations / maintenance, so a fleet larger than
 * one page silently lost interval rows. A vehicle whose reservation row was
 * dropped then showed a frozen status forever — the BoundaryTicker had no edge
 * to schedule. This suite proves the fix:
 *
 *   authoritative snapshot  ->  ONE atomic Room apply  ->  EVERY interval row
 *   present locally  ->  completeness flag + revision watermark set  ->  a
 *   stale snapshot can never overwrite a newer one.
 */
@RunWith(RobolectricTestRunner::class)
class MobileTemporalCacheCompletenessTest {

    private lateinit var db: AppDatabase
    private lateinit var repo: FleetRepository

    @Before
    fun setup() {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        db = Room.inMemoryDatabaseBuilder(context, AppDatabase::class.java)
            .allowMainThreadQueries()
            .build()
        // Pin the API endpoint to an unroutable local address: this suite must
        // never contact a real server (and definitely not production).
        val tm = TokenManager(context).apply { saveBaseUrl("http://127.0.0.1:1/api/v1/") }
        repo = FleetRepository(ApiClient(tm), db, context, nowMillis = { BASE })
    }

    @After
    fun tearDown() = db.close()

    private val BASE = FleetStatus.parseUtcMillis("2026-08-30T12:00:00Z")!!

    private fun veh(id: String, status: String = "AVAILABLE") = VehicleDto(
        id = id, registration = "R-$id", brand = "B", model = "M", year = 2024,
        status = status, effectiveStatus = status,
    )

    private fun rental(id: String, vid: String, startIso: String, endIso: String, status: String = "ACTIVE") =
        RentalDto(id = id, vehicleId = vid, startDatetime = startIso, endDatetime = endIso, status = status)

    private fun maint(id: String, vid: String, startIso: String, endIso: String?, status: String = "ACTIVE") =
        MaintenanceDto(id = id, vehicleId = vid, startDatetime = startIso, expectedEndDatetime = endIso, status = status)

    private fun snapshot(
        revision: Long,
        vehicles: List<VehicleDto>,
        rentals: List<RentalDto> = emptyList(),
        maintenance: List<MaintenanceDto> = emptyList(),
    ) = SyncBootstrapResponseDto(
        syncVersion = 1, revision = revision, serverTime = "2026-08-30T12:00:00Z",
        vehicles = vehicles, rentals = rentals, maintenance = maintenance, notifications = emptyList(),
    )

    // ── FULL-SYNC COMPLETENESS ───────────────────────────────────────────
    @Test
    fun `full snapshot larger than one API page lands complete and atomic`() = runBlocking {
        // 260 vehicles, 240 reservations, 130 maintenance — well past every
        // list-endpoint page cap (100 / 100 / 500).
        val vehicles = (1..260).map { veh("v$it") }
        val rentals = (1..240).map {
            rental("r$it", "v$it", "2026-08-29T00:00:00Z", "2026-09-05T00:00:00Z")
        }
        val maintenance = (1..130).map {
            maint("m$it", "v$it", "2026-08-01T00:00:00Z", "2026-08-02T00:00:00Z", status = "COMPLETED")
        }

        val applied = repo.applyAuthoritativeSnapshot(snapshot(1_000L, vehicles, rentals, maintenance))
        assertTrue(applied)

        assertEquals(260, db.vehicleDao().getAllVehicles().first().size)
        assertEquals(240, db.reservationDao().getAllReservations().first().size)
        assertEquals(130, db.maintenanceDao().getAllTickets().first().size)

        // completeness invariant: EVERY vehicle that has an interval row in the
        // snapshot has that interval row locally (machine-parseable ISO edges).
        val resVids = db.reservationDao().getAllReservations().first()
            .filter { it.startDatetimeIso.isNotBlank() && it.endDatetimeIso.isNotBlank() }
            .map { it.vehicleId }.toSet()
        assertEquals((1..240).map { "v$it" }.toSet(), resVids)

        assertTrue(repo.cacheCompleteFlow.first())
        assertEquals(1_000L, repo.localRevision())
    }

    @Test
    fun `atomic apply replaces the whole projection - no leftover stale rows`() = runBlocking {
        repo.applyAuthoritativeSnapshot(
            snapshot(10L, listOf(veh("a"), veh("b")), listOf(rental("r-old", "a", "2026-08-29T00:00:00Z", "2026-09-01T00:00:00Z")))
        )
        // second snapshot drops vehicle b and the old reservation, adds c
        repo.applyAuthoritativeSnapshot(
            snapshot(20L, listOf(veh("a"), veh("c")), listOf(rental("r-new", "c", "2026-08-29T00:00:00Z", "2026-09-01T00:00:00Z")))
        )
        assertEquals(setOf("a", "c"), db.vehicleDao().getAllVehicles().first().map { it.id }.toSet())
        assertEquals(listOf("r-new"), db.reservationDao().getAllReservations().first().map { it.id })
        assertEquals(20L, repo.localRevision())
    }

    // ── REVISION SAFETY ──────────────────────────────────────────────────
    @Test
    fun `stale snapshot is rejected, duplicate is idempotent, watermark never regresses`() = runBlocking {
        assertTrue(repo.applyAuthoritativeSnapshot(snapshot(5_000L, listOf(veh("a")))))
        assertEquals(5_000L, repo.localRevision())

        // stale (older revision) — rejected, cache untouched
        assertFalse(repo.applyAuthoritativeSnapshot(snapshot(3_000L, listOf(veh("a"), veh("STALE")))))
        assertEquals(setOf("a"), db.vehicleDao().getAllVehicles().first().map { it.id }.toSet())
        assertEquals(5_000L, repo.localRevision())

        // duplicate (equal revision) — applied idempotently
        assertTrue(repo.applyAuthoritativeSnapshot(snapshot(5_000L, listOf(veh("a")))))
        assertEquals(5_000L, repo.localRevision())

        // newer — applied, watermark advances
        assertTrue(repo.applyAuthoritativeSnapshot(snapshot(9_000L, listOf(veh("a"), veh("b")))))
        assertEquals(9_000L, repo.localRevision())

        // revision 0 (empty-fleet sentinel) never drags the watermark back
        assertTrue(repo.applyAuthoritativeSnapshot(snapshot(0L, listOf(veh("a")))))
        assertEquals(9_000L, repo.localRevision())
    }

    @Test
    fun `fresh cache is not complete until a snapshot is applied`() = runBlocking {
        assertFalse(repo.cacheCompleteFlow.first())
        assertEquals(-1L, repo.localRevision())
        repo.applyAuthoritativeSnapshot(snapshot(1L, listOf(veh("a"))))
        assertTrue(repo.cacheCompleteFlow.first())
    }
}
