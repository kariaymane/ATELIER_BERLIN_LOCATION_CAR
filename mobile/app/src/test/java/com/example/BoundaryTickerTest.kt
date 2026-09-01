package com.example

import com.example.data.fleet.BoundaryTicker
import com.example.data.fleet.FleetStatus
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.test.advanceTimeBy
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

@OptIn(ExperimentalCoroutinesApi::class)
class BoundaryTickerTest {

    private val base = FleetStatus.parseUtcMillis("2026-08-30T12:00:00Z")!!

    private fun res(vid: String, startIso: String, endIso: String, status: String = "ACTIVE") =
        FleetStatus.ReservationRow(vid, status, startIso, endIso)

    private fun maint(vid: String, startIso: String, endIso: String?, status: String = "ACTIVE") =
        FleetStatus.MaintenanceRow(vid, status, startIso, endIso, null)

    private fun emptyIntervals() =
        MutableStateFlow(emptyList<FleetStatus.ReservationRow>() to emptyList<FleetStatus.MaintenanceRow>())

    @Test
    fun `no boundary emits only the priming tick`() = runTest {
        val sched = testScheduler
        val now = { base + sched.currentTime }
        val ticker = BoundaryTicker(nowMillis = now, delayFn = ::delay, includeMidnight = false)
        val ticks = mutableListOf<Long>()
        val job = launch { ticker.ticks(emptyIntervals()).collect { ticks.add(it) } }

        runCurrent()
        assertEquals(1, ticks.size)
        advanceUntilIdle()
        assertEquals("no future edge → no further ticks", 1, ticks.size)
        job.cancel()
    }

    @Test
    fun `one boundary emits one tick at the exact instant`() = runTest {
        val sched = testScheduler
        val now = { base + sched.currentTime }
        val ticker = BoundaryTicker(nowMillis = now, delayFn = ::delay, includeMidnight = false)
        val intervals = MutableStateFlow(
            listOf(res("v1", "2026-08-30T10:00:00Z", "2026-08-30T15:00:00Z")) to
                emptyList<FleetStatus.MaintenanceRow>()
        )
        val ticks = mutableListOf<Long>()
        val job = launch { ticker.ticks(intervals).collect { ticks.add(it) } }

        runCurrent()
        assertEquals(1, ticks.size)                // prime
        advanceTimeBy(3 * 3600_000 - 1)            // 14:59:59.999
        runCurrent()
        assertEquals(1, ticks.size)                // not yet
        advanceTimeBy(1)                           // 15:00:00.000 exactly
        runCurrent()
        assertEquals(2, ticks.size)
        assertEquals(FleetStatus.parseUtcMillis("2026-08-30T15:00:00Z"), ticks[1])
        job.cancel()
    }

    @Test
    fun `multiple boundaries fire in order, one at a time, never polling`() = runTest {
        val sched = testScheduler
        val now = { base + sched.currentTime }
        var maxConcurrentDelays = 0
        var activeDelays = 0
        val trackingDelay: suspend (Long) -> Unit = { ms ->
            activeDelays++; maxConcurrentDelays = maxOf(maxConcurrentDelays, activeDelays)
            try { delay(ms) } finally { activeDelays-- }
        }
        val ticker = BoundaryTicker(nowMillis = now, delayFn = trackingDelay, includeMidnight = false)
        val intervals = MutableStateFlow(
            listOf(
                res("a", "2026-08-30T10:00:00Z", "2026-08-30T12:05:00Z"),
                res("b", "2026-08-30T10:00:00Z", "2026-08-30T12:10:00Z"),
                res("c", "2026-08-30T10:00:00Z", "2026-08-30T12:15:00Z"),
            ) to emptyList<FleetStatus.MaintenanceRow>()
        )
        val ticks = mutableListOf<Long>()
        val job = launch { ticker.ticks(intervals).collect { ticks.add(it) } }

        runCurrent()
        advanceTimeBy(5 * 60_000); runCurrent()    // 12:05
        advanceTimeBy(5 * 60_000); runCurrent()    // 12:10
        advanceTimeBy(5 * 60_000); runCurrent()    // 12:15
        advanceUntilIdle()

        // prime + 3 boundary ticks = 4 (NOT one-per-second)
        assertEquals(4, ticks.size)
        assertEquals(FleetStatus.parseUtcMillis("2026-08-30T12:05:00Z"), ticks[1])
        assertEquals(FleetStatus.parseUtcMillis("2026-08-30T12:10:00Z"), ticks[2])
        assertEquals(FleetStatus.parseUtcMillis("2026-08-30T12:15:00Z"), ticks[3])
        assertEquals("exactly one wait outstanding at any time", 1, maxConcurrentDelays)
        job.cancel()
    }

    @Test
    fun `sync with an earlier boundary invalidates the pending wait`() = runTest {
        val sched = testScheduler
        val now = { base + sched.currentTime }
        val ticker = BoundaryTicker(nowMillis = now, delayFn = ::delay, includeMidnight = false)
        val intervals = MutableStateFlow(
            listOf(res("v1", "2026-08-30T10:00:00Z", "2026-08-30T18:00:00Z")) to
                emptyList<FleetStatus.MaintenanceRow>()
        )
        val ticks = mutableListOf<Long>()
        val job = launch { ticker.ticks(intervals).collect { ticks.add(it) } }
        runCurrent()

        advanceTimeBy(60 * 60_000)  // 13:00, still waiting for the 18:00 edge
        runCurrent()
        assertEquals(1, ticks.size)

        // a sync brings a NEW earlier reservation ending at 13:30
        intervals.value = listOf(
            res("v1", "2026-08-30T10:00:00Z", "2026-08-30T18:00:00Z"),
            res("v2", "2026-08-30T10:00:00Z", "2026-08-30T13:30:00Z"),
        ) to emptyList()
        runCurrent()

        advanceTimeBy(30 * 60_000)  // 13:30
        runCurrent()
        assertEquals("fired at the NEW earliest boundary, not the stale one", 2, ticks.size)
        assertEquals(FleetStatus.parseUtcMillis("2026-08-30T13:30:00Z"), ticks[1])
        job.cancel()
    }

    @Test
    fun `stop (collector cancel) leaves no running work`() = runTest {
        val sched = testScheduler
        val now = { base + sched.currentTime }
        val ticker = BoundaryTicker(nowMillis = now, delayFn = ::delay, includeMidnight = false)
        val intervals = MutableStateFlow(
            listOf(res("v1", "2026-08-30T10:00:00Z", "2026-08-30T18:00:00Z")) to
                emptyList<FleetStatus.MaintenanceRow>()
        )
        val ticks = mutableListOf<Long>()
        val job = launch { ticker.ticks(intervals).collect { ticks.add(it) } }
        runCurrent()
        job.cancel()
        advanceUntilIdle()
        assertEquals(1, ticks.size)
        assertTrue(job.isCancelled)
    }

    @Test
    fun `restart re-arms the schedule`() = runTest {
        val sched = testScheduler
        val now = { base + sched.currentTime }
        val ticker = BoundaryTicker(nowMillis = now, delayFn = ::delay, includeMidnight = false)
        val intervals = MutableStateFlow(
            listOf(res("v1", "2026-08-30T10:00:00Z", "2026-08-30T13:00:00Z")) to
                emptyList<FleetStatus.MaintenanceRow>()
        )

        val ticks1 = mutableListOf<Long>()
        val job1 = launch { ticker.ticks(intervals).collect { ticks1.add(it) } }
        runCurrent()
        job1.cancel()

        val ticks2 = mutableListOf<Long>()
        val job2 = launch { ticker.ticks(intervals).collect { ticks2.add(it) } }
        runCurrent()
        advanceTimeBy(60 * 60_000); runCurrent()   // 13:00
        assertEquals(2, ticks2.size)               // prime + boundary on the fresh collection
        job2.cancel()
    }

    @Test
    fun `maintenance boundary`() = runTest {
        val sched = testScheduler
        val now = { base + sched.currentTime }
        val ticker = BoundaryTicker(nowMillis = now, delayFn = ::delay, includeMidnight = false)
        val intervals = MutableStateFlow(
            emptyList<FleetStatus.ReservationRow>() to
                listOf(maint("v1", "2026-08-30T10:00:00Z", "2026-08-30T12:20:00Z"))
        )
        val ticks = mutableListOf<Long>()
        val job = launch { ticker.ticks(intervals).collect { ticks.add(it) } }
        runCurrent()
        advanceTimeBy(20 * 60_000); runCurrent()   // 12:20
        assertEquals(2, ticks.size)
        assertEquals(FleetStatus.parseUtcMillis("2026-08-30T12:20:00Z"), ticks[1])
        job.cancel()
    }

    @Test
    fun `midnight is a boundary when includeMidnight is on`() = runTest {
        // base = 2026-08-30T12:00:00Z. Africa/Casablanca is UTC+1 in Aug (DST),
        // so local midnight 2026-08-31T00:00 local == 2026-08-30T23:00Z.
        val sched = testScheduler
        val now = { base + sched.currentTime }
        val ticker = BoundaryTicker(nowMillis = now, delayFn = ::delay, includeMidnight = true)
        val ticks = mutableListOf<Long>()
        val job = launch { ticker.ticks(emptyIntervals()).collect { ticks.add(it) } }
        runCurrent()
        assertEquals(1, ticks.size)

        val midnight = FleetStatus.nextMidnightMillis(base)
        advanceTimeBy(midnight - base); runCurrent()
        assertEquals("ticked at local midnight with no interval data at all", 2, ticks.size)
        assertEquals(midnight, ticks[1])
        job.cancel()
    }
}
