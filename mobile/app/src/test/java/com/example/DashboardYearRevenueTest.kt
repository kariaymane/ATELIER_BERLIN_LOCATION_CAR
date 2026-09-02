package com.example

import com.example.data.fleet.FleetStatus
import org.junit.Assert.assertEquals
import org.junit.Test
import java.text.SimpleDateFormat
import java.util.Calendar
import java.util.Locale
import java.util.TimeZone

/**
 * Mobile `FleetStatus.dashboardOverview` — year-to-date revenue.
 *
 * Same canonical recognition-at-start rule as backend `get_revenue_between`
 * and desktop `compute_overview_rows` (a wider window, NOT a new formula):
 *   status != CANCELLED  AND  start <= now  AND  start in [yearStart, nextYear)
 *
 * Guards the case that motivated the change: the today/week/month cards are
 * legitimately 0 when nothing started in that period, while `year_revenue`
 * still shows the real turnover.
 */
class DashboardYearRevenueTest {

    private val CASA = TimeZone.getTimeZone("Africa/Casablanca")

    private fun iso(ms: Long): String =
        SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss", Locale.US)
            .apply { timeZone = TimeZone.getTimeZone("UTC") }
            .format(java.util.Date(ms))

    private fun casaMillis(year: Int, month0: Int, day: Int, hour: Int = 9): Long =
        Calendar.getInstance(CASA, Locale.US).apply {
            clear(); set(year, month0, day, hour, 0, 0)
        }.timeInMillis

    @Test
    fun `year revenue sums every started non-cancelled rental this year, month stays zero`() {
        // "now" = 2 Sept, 12:00 Casablanca
        val now = casaMillis(2026, Calendar.SEPTEMBER, 2, 12)

        val v = listOf(FleetStatus.VehicleRow("v1", "AVAILABLE"),
                       FleetStatus.VehicleRow("v2", "AVAILABLE"))
        val res = listOf(
            // started in Jan + Feb 2026 -> counts for the YEAR, not this month/week
            FleetStatus.ReservationRow("v1", "COMPLETED",
                iso(casaMillis(2026, Calendar.JANUARY, 15)), iso(casaMillis(2026, Calendar.JANUARY, 18)), 5000.0),
            FleetStatus.ReservationRow("v2", "ACTIVE",
                iso(casaMillis(2026, Calendar.FEBRUARY, 20)), iso(now + 5L * 86_400_000L), 3000.0),
            // CANCELLED -> excluded
            FleetStatus.ReservationRow("v1", "CANCELLED",
                iso(casaMillis(2026, Calendar.MARCH, 1)), iso(casaMillis(2026, Calendar.MARCH, 3)), 9999.0),
            // next year -> outside the window
            FleetStatus.ReservationRow("v2", "RESERVED",
                iso(casaMillis(2027, Calendar.JANUARY, 10)), iso(casaMillis(2027, Calendar.JANUARY, 12)), 7777.0),
        )

        val ov = FleetStatus.dashboardOverview(v, res, emptyList(), now, CASA)

        assertEquals(8000.0, ov.yearRevenue, 0.001)   // 5000 + 3000
        assertEquals(2, ov.yearBookings)
        assertEquals(0.0, ov.monthRevenue, 0.001)     // nothing started in September
        assertEquals(0.0, ov.weekRevenue, 0.001)
    }
}
