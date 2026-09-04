package com.example

import com.example.data.fleet.FleetStatus
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Test
import java.util.Calendar
import java.util.Locale
import java.util.TimeZone

/**
 * R5 — PERMANENT GUARD: the ONE naive-datetime policy, Kotlin side.
 *
 * A datetime with no UTC offset is BUSINESS-LOCAL wall time (Africa/Casablanca),
 * never UTC. The Python side of this guard is
 * `backend/tests/test_naive_datetime_policy.py`; both assert the SAME instants,
 * so if either runtime drifts the pair stops agreeing and one of them goes red.
 *
 * This is the defect (W1) these tests exist to prevent: `parseUtcMillis` read
 * offset-less values as UTC while Backend/Desktop/`shared` read them as
 * business-local, so for the SAME reservation row at the SAME instant Desktop
 * showed "en location = 1" and Mobile showed "en location = 0, réservés = 1".
 * Nothing caught it, because every interval literal in the shared parity
 * vectors carried an explicit `Z`.
 */
class NaiveDatetimePolicyTest {

    private val biz: TimeZone = TimeZone.getTimeZone("Africa/Casablanca")

    /** Epoch-millis of a wall-clock reading in an explicit zone. */
    private fun at(zone: TimeZone, y: Int, mo: Int, d: Int, h: Int, mi: Int): Long =
        Calendar.getInstance(zone, Locale.US).apply {
            clear(); set(y, mo - 1, d, h, mi, 0)
        }.timeInMillis

    // The literal and the instant the ONE policy says it denotes. Mirrors
    // NAIVE_LITERAL / EXPECTED_INSTANT in the Python guard.
    private val naiveLiteral = "2026-08-30T13:00:00"
    private val expectedInstant get() = at(biz, 2026, 8, 30, 13, 0)   // == 12:00Z

    @Test
    fun `a naive literal is business-local wall time, not UTC`() {
        val utcReading = at(TimeZone.getTimeZone("UTC"), 2026, 8, 30, 13, 0)
        // Guard against a vacuous test: the two readings must actually differ.
        assertNotEquals(
            "pick a literal where business-local and UTC differ",
            utcReading, expectedInstant,
        )
        assertEquals(
            "naive must be read as Africa/Casablanca",
            expectedInstant, FleetStatus.parseUtcMillis(naiveLiteral),
        )
    }

    @Test
    fun `every offset-less accepted form resolves to the same business-local instant`() {
        for (form in listOf(
            "2026-08-30T13:00:00",      // ISO naive
            "2026-08-30 13:00:00",      // SQLite round-trip form
            "2026-08-30T13:00",         // minute precision
        )) {
            assertEquals(form, expectedInstant, FleetStatus.parseUtcMillis(form))
        }
        // A naive DATE is business-local midnight.
        assertEquals(
            at(biz, 2026, 8, 30, 0, 0),
            FleetStatus.parseUtcMillis("2026-08-30"),
        )
    }

    @Test
    fun `an explicit offset is honoured as written and never re-interpreted`() {
        val noon = at(TimeZone.getTimeZone("UTC"), 2026, 8, 30, 12, 0)
        assertEquals(noon, FleetStatus.parseUtcMillis("2026-08-30T12:00:00Z"))
        assertEquals(noon, FleetStatus.parseUtcMillis("2026-08-30T12:00:00+00:00"))
        assertEquals(noon, FleetStatus.parseUtcMillis("2026-08-30T13:00:00+01:00"))
        // fractional seconds must not change the instant
        assertEquals(noon, FleetStatus.parseUtcMillis("2026-08-30T12:00:00.123456Z"))
    }

    @Test
    fun `reservation half-open boundaries on a naive row match the canonical rule`() {
        val vehicles = listOf(FleetStatus.VehicleRow("v1", "AVAILABLE"))
        // Stored naive, business-local: 09:00 -> 13:00 Casablanca.
        val res = listOf(
            FleetStatus.ReservationRow("v1", "RESERVED", "2026-08-30T09:00:00", "2026-08-30T13:00:00")
        )
        val start = at(biz, 2026, 8, 30, 9, 0)
        val end = at(biz, 2026, 8, 30, 13, 0)
        val minute = 60_000L

        fun eff(now: Long) = FleetStatus.effectiveStatuses(vehicles, res, emptyList(), now)["v1"]

        assertEquals("before start -> upcoming", FleetStatus.RESERVED, eff(start - minute))
        assertEquals("exactly at start -> occupied", FleetStatus.RENTED, eff(start))
        assertEquals("during -> occupied", FleetStatus.RENTED, eff(start + minute))
        assertEquals("just before end -> occupied", FleetStatus.RENTED, eff(end - minute))
        assertEquals("exactly at end -> free", FleetStatus.AVAILABLE, eff(end))
        assertEquals("after end -> free", FleetStatus.AVAILABLE, eff(end + minute))
    }

    @Test
    fun `maintenance half-open boundaries on a naive row match the canonical rule`() {
        val vehicles = listOf(FleetStatus.VehicleRow("v1", "AVAILABLE"))
        val maint = listOf(
            FleetStatus.MaintenanceRow(
                "v1", "ACTIVE", "2026-08-30T09:00:00", "2026-08-30T13:00:00", null
            )
        )
        val start = at(biz, 2026, 8, 30, 9, 0)
        val end = at(biz, 2026, 8, 30, 13, 0)
        val minute = 60_000L

        fun eff(now: Long) = FleetStatus.effectiveStatuses(vehicles, emptyList(), maint, now)["v1"]

        assertEquals(FleetStatus.AVAILABLE, eff(start - minute))
        assertEquals("exactly at start -> occupied", FleetStatus.MAINTENANCE, eff(start))
        assertEquals(FleetStatus.MAINTENANCE, eff(end - minute))
        assertEquals("exactly at end -> free", FleetStatus.AVAILABLE, eff(end))
    }

    @Test
    fun `actual_end wins over expected_end`() {
        val vehicles = listOf(FleetStatus.VehicleRow("v1", "AVAILABLE"))
        val maint = listOf(
            FleetStatus.MaintenanceRow(
                "v1", "ACTIVE",
                startIso = "2026-08-30T08:00:00",
                expectedEndIso = "2026-09-05T10:00:00",  // stale estimate
                actualEndIso = "2026-08-30T10:00:00",    // closed early — wins
            )
        )
        val now = at(biz, 2026, 8, 30, 12, 0)
        assertEquals(
            FleetStatus.AVAILABLE,
            FleetStatus.effectiveStatuses(vehicles, emptyList(), maint, now)["v1"],
        )
    }

    /**
     * The exact contradiction from the production report, pinned. A naive
     * reservation window that contains `now` under the business-local reading
     * but NOT under a UTC reading must classify as RENTED — the answer Desktop
     * and Backend give for the same row.
     */
    @Test
    fun `W1 regression - naive window covering now is RENTED, matching Desktop and Backend`() {
        val vehicles = listOf(FleetStatus.VehicleRow("v1", "AVAILABLE"))
        val res = listOf(
            FleetStatus.ReservationRow("v1", "RESERVED", "2026-08-30T12:30:00", "2026-08-30T14:30:00")
        )
        val now = at(TimeZone.getTimeZone("UTC"), 2026, 8, 30, 12, 0)  // 13:00 Casablanca

        val got = FleetStatus.effectiveStatuses(vehicles, res, emptyList(), now)["v1"]
        assertEquals(
            "naive==UTC would have said RESERVED and contradicted Desktop/Backend",
            FleetStatus.RENTED, got,
        )

        val counts = FleetStatus.fleetCounts(vehicles, res, emptyList(), now)
        assertEquals(1, counts["rented"])
        assertEquals(0, counts["reserved"])
        assertEquals(0, counts["available"])
    }
}
