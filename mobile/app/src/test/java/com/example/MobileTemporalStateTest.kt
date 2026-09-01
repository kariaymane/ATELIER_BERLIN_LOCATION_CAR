package com.example

import com.example.data.fleet.BoundaryTicker
import com.example.data.fleet.FleetStatus
import com.example.data.local.VehicleEntity
import com.example.data.model.VehicleStatus
import com.example.data.repository.FleetRepository
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.launch
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.test.advanceTimeBy
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Increment 4 — mobile temporal state.
 *
 * Reproduces the EXACT `combine(vehicles, intervals, boundaryTicks) { deriveEffectiveVehicles(...) }`
 * pipeline of `FleetRepository.vehiclesFlow`, and proves the decisive property:
 *
 *   TIME PASSES → the vehicle's effective status changes → the flow emits,
 *   with NO API request, NO Room mutation, NO manual refresh, NO navigation,
 *   NO UI click.
 */
@OptIn(ExperimentalCoroutinesApi::class)
class MobileTemporalStateTest {

    private fun v(id: String, status: String = "RENTED") =
        VehicleEntity(id, "B", "M", "P-$id", 2024, "Berline", 100, status, 0, "", "", "", "",
            "", "", "", "", 0, 1)

    private fun res(vid: String, startIso: String, endIso: String, status: String = "ACTIVE") =
        FleetStatus.ReservationRow(vid, status, startIso, endIso)

    /** The vehiclesFlow pipeline, verbatim, over injectable inputs. */
    private fun pipeline(
        vehicles: MutableStateFlow<List<VehicleEntity>>,
        intervals: MutableStateFlow<Pair<List<FleetStatus.ReservationRow>, List<FleetStatus.MaintenanceRow>>>,
        now: () -> Long,
        delayFn: suspend (Long) -> Unit,
    ) = combine(
        vehicles,
        intervals,
        BoundaryTicker(nowMillis = now, delayFn = delayFn, includeMidnight = true).ticks(intervals),
    ) { vEntities, iv, _tick ->
        FleetRepository.deriveEffectiveVehicles(vEntities, iv.first, iv.second, now())
    }.distinctUntilChanged()

    @Test
    fun `reservation end frees the vehicle purely because time passed`() = runTest {
        val base = FleetStatus.parseUtcMillis("2026-08-30T12:00:00Z")!!
        val end = "2026-08-30T12:00:05Z"                 // ends in 5 virtual seconds
        val sched = testScheduler
        val now = { base + sched.currentTime }

        val vehicles = MutableStateFlow(listOf(v("veh-1", status = "RENTED")))
        val intervals = MutableStateFlow(
            listOf(res("veh-1", "2026-08-30T10:00:00Z", end)) to emptyList<FleetStatus.MaintenanceRow>()
        )

        val emissions = mutableListOf<VehicleStatus>()
        val job = launch {
            pipeline(vehicles, intervals, now, ::delay).collect { list ->
                emissions.add(list.first { it.id == "veh-1" }.status)
            }
        }

        runCurrent()
        assertEquals(VehicleStatus.EN_LOCATION, emissions.last())   // RENTED before

        // DO NOTHING but let virtual time advance to the exact boundary
        advanceTimeBy(5_000)
        runCurrent()

        assertEquals(VehicleStatus.DISPONIBLE, emissions.last())    // AVAILABLE at end
        // one meaningful transition emission (distinctUntilChanged collapses noise)
        assertEquals(listOf(VehicleStatus.EN_LOCATION, VehicleStatus.DISPONIBLE), emissions)

        // nothing was mutated
        assertEquals(1, vehicles.value.size)
        assertEquals("RENTED", vehicles.value.first().status)       // Room row untouched
        job.cancel()
    }

    @Test
    fun `multiple reservation ends transition one by one`() = runTest {
        val base = FleetStatus.parseUtcMillis("2026-08-30T12:00:00Z")!!
        val sched = testScheduler
        val now = { base + sched.currentTime }
        val vehicles = MutableStateFlow(listOf(v("a"), v("b"), v("c")))
        val intervals = MutableStateFlow(
            listOf(
                res("a", "2026-08-30T10:00:00Z", "2026-08-30T12:00:05Z"),
                res("b", "2026-08-30T10:00:00Z", "2026-08-30T12:00:10Z"),
                res("c", "2026-08-30T10:00:00Z", "2026-08-30T12:00:15Z"),
            ) to emptyList<FleetStatus.MaintenanceRow>()
        )
        val snapshots = mutableListOf<Map<String, VehicleStatus>>()
        val job = launch {
            pipeline(vehicles, intervals, now, ::delay).collect { list ->
                snapshots.add(list.associate { it.id to it.status })
            }
        }
        runCurrent()
        assertEquals(3, snapshots.last().values.count { it == VehicleStatus.EN_LOCATION })

        advanceTimeBy(5_000); runCurrent()
        assertEquals(VehicleStatus.DISPONIBLE, snapshots.last()["a"])
        assertEquals(VehicleStatus.EN_LOCATION, snapshots.last()["b"])

        advanceTimeBy(5_000); runCurrent()
        assertEquals(VehicleStatus.DISPONIBLE, snapshots.last()["b"])
        assertEquals(VehicleStatus.EN_LOCATION, snapshots.last()["c"])

        advanceTimeBy(5_000); runCurrent()
        assertEquals(3, snapshots.last().values.count { it == VehicleStatus.DISPONIBLE })
        job.cancel()
    }

    @Test
    fun `a sync that lands near a boundary — newest data wins, no stale overwrite`() = runTest {
        val base = FleetStatus.parseUtcMillis("2026-08-30T12:00:00Z")!!
        val sched = testScheduler
        val now = { base + sched.currentTime }
        val vehicles = MutableStateFlow(listOf(v("veh-1")))
        val intervals = MutableStateFlow(
            listOf(res("veh-1", "2026-08-30T10:00:00Z", "2026-08-30T12:00:05Z")) to
                emptyList<FleetStatus.MaintenanceRow>()
        )
        val emissions = mutableListOf<VehicleStatus>()
        val job = launch {
            pipeline(vehicles, intervals, now, ::delay).collect { list ->
                emissions.add(list.first().status)
            }
        }
        runCurrent()

        // just before the boundary a sync extends the reservation
        advanceTimeBy(4_000); runCurrent()
        intervals.value = listOf(
            res("veh-1", "2026-08-30T10:00:00Z", "2026-08-30T13:00:00Z")
        ) to emptyList()
        runCurrent()

        advanceTimeBy(2_000); runCurrent()   // past the OLD 12:00:05 edge
        assertEquals("newest data wins — still RENTED", VehicleStatus.EN_LOCATION, emissions.last())

        advanceTimeBy(60 * 60_000); runCurrent()   // past the NEW 13:00 edge
        assertEquals(VehicleStatus.DISPONIBLE, emissions.last())
        job.cancel()
    }

    // ── MIDNIGHT — dashboard period rollover ─────────────────────────────
    @Test
    fun `local midnight rolls the dashboard period cards`() {
        val tz = java.util.TimeZone.getTimeZone("Africa/Casablanca")
        fun local(y: Int, mo: Int, d: Int, h: Int, mi: Int): Long {
            val c = java.util.Calendar.getInstance(tz, java.util.Locale.US)
            c.set(y, mo - 1, d, h, mi, 0); c.set(java.util.Calendar.MILLISECOND, 0)
            return c.timeInMillis
        }
        fun iso(ms: Long): String {
            val sdf = java.text.SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss", java.util.Locale.US)
            sdf.timeZone = java.util.TimeZone.getTimeZone("UTC"); return sdf.format(java.util.Date(ms))
        }
        // Wed 26 Aug -> Thu 27 Aug: only the day rolls (same week, same month).
        val beforeMidnight = local(2026, 8, 26, 23, 59)
        val afterMidnight = local(2026, 8, 27, 0, 1)
        val resStart = local(2026, 8, 26, 12, 0)

        val vehicles = listOf(FleetStatus.VehicleRow("v1", "AVAILABLE"))
        val reservations = listOf(
            FleetStatus.ReservationRow(
                "v1", "ACTIVE", iso(resStart), iso(resStart + 5L * 86_400_000L), 500.0,
            )
        )

        val before = FleetStatus.dashboardOverview(vehicles, reservations, emptyList(), beforeMidnight)
        assertEquals(500.0, before.todayRevenue, 0.001)
        assertEquals(1, before.todayBookings)
        assertEquals(500.0, before.weekRevenue, 0.001)

        val after = FleetStatus.dashboardOverview(vehicles, reservations, emptyList(), afterMidnight)
        assertEquals("today revenue resets on the new local day", 0.0, after.todayRevenue, 0.001)
        assertEquals(0, after.todayBookings)
        assertEquals("still the same week", 500.0, after.weekRevenue, 0.001)
        assertEquals("still the same month", 500.0, after.monthRevenue, 0.001)
    }

    @Test
    fun `dashboard metrics flow re-emits at the midnight tick with no mutation`() = runTest {
        val tz = java.util.TimeZone.getTimeZone("Africa/Casablanca")
        val sched = testScheduler
        // start at 23:59:30 local
        val c = java.util.Calendar.getInstance(tz, java.util.Locale.US)
        c.set(2026, 7, 26, 23, 59, 30); c.set(java.util.Calendar.MILLISECOND, 0)
        val base = c.timeInMillis
        val now = { base + sched.currentTime }

        fun iso(ms: Long): String {
            val sdf = java.text.SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss", java.util.Locale.US)
            sdf.timeZone = java.util.TimeZone.getTimeZone("UTC"); return sdf.format(java.util.Date(ms))
        }
        val resStart = base - 12L * 3600_000L
        val vehicles = MutableStateFlow(listOf(v("v1", status = "AVAILABLE")))
        val intervals = MutableStateFlow(
            listOf(FleetStatus.ReservationRow("v1", "ACTIVE", iso(resStart), iso(base + 5L * 86_400_000L), 500.0))
                to emptyList<FleetStatus.MaintenanceRow>()
        )

        val metrics = mutableListOf<Double>()   // today revenue over time
        val job = launch {
            combine(
                vehicles, intervals,
                BoundaryTicker(nowMillis = now, delayFn = ::delay, includeMidnight = true).ticks(intervals),
            ) { v, iv, _ ->
                FleetStatus.dashboardOverview(
                    v.map { FleetStatus.VehicleRow(it.id, it.status) }, iv.first, iv.second, now(),
                ).todayRevenue
            }.distinctUntilChanged().collect { metrics.add(it) }
        }

        runCurrent()
        assertEquals(500.0, metrics.last(), 0.001)   // before midnight

        advanceTimeBy(60_000); runCurrent()          // cross 00:00 local
        assertEquals("rolled to the new day with NO mutation, NO refresh", 0.0, metrics.last(), 0.001)
        job.cancel()
    }

    // ── REAL clock — the decisive proof (short, ~2s) ─────────────────────
    @Test
    fun `REAL clock — vehicle frees itself with zero user action`() = runBlocking {
        val start = System.currentTimeMillis()
        val endMs = start + 2_000
        val endIso = FleetStatus.let {
            val sdf = java.text.SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss", java.util.Locale.US)
            sdf.timeZone = java.util.TimeZone.getTimeZone("UTC")
            sdf.format(java.util.Date(endMs))
        }
        val startIso = run {
            val sdf = java.text.SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss", java.util.Locale.US)
            sdf.timeZone = java.util.TimeZone.getTimeZone("UTC")
            sdf.format(java.util.Date(start - 3_600_000))
        }

        val vehicles = MutableStateFlow(listOf(v("veh-real")))
        val intervals = MutableStateFlow(
            listOf(res("veh-real", startIso, endIso)) to emptyList<FleetStatus.MaintenanceRow>()
        )
        val emissions = mutableListOf<VehicleStatus>()
        val job = launch {
            pipeline(vehicles, intervals, { System.currentTimeMillis() }, { delay(it) }).collect {
                emissions.add(it.first().status)
            }
        }

        // observe RENTED
        while (emissions.isEmpty()) delay(10)
        val oldStatus = emissions.last()
        assertEquals(VehicleStatus.EN_LOCATION, oldStatus)

        // DO NOTHING — wait past the real boundary
        val deadline = endMs + 2_000
        while (System.currentTimeMillis() < deadline && emissions.last() != VehicleStatus.DISPONIBLE) {
            delay(50)
        }

        val newStatus = emissions.last()
        println("=== MOBILE FORENSIC TEMPORAL TRANSITION ===")
        println("boundary timestamp : $endIso")
        println("old status         : $oldStatus")
        println("new status         : $newStatus")
        println("emission count     : ${emissions.size}")

        assertEquals(VehicleStatus.DISPONIBLE, newStatus)
        assertEquals("RENTED", vehicles.value.first().status)  // Room row never touched
        assertTrue(emissions.size >= 2)
        job.cancel()
    }
}
