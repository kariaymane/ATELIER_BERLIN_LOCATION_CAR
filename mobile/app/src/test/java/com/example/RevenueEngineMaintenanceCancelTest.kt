package com.example

import com.example.data.fleet.RevenueEngine
import org.junit.Assert.assertEquals
import org.junit.Test
import java.math.BigDecimal

/**
 * v1.1.0 audit P1-A / P1-B regression (mobile side):
 *  - a rental CANCELLED for MAINTENANCE still contributes the days realised
 *    BEFORE the interruption (parity with backend + desktop + shared spec);
 *  - that number is STABLE — it does not grow once the clock passes the
 *    original end (no `cancelledAt` -> falls back to `endMillis`, capped);
 *  - a plain manual CANCELLED still contributes zero.
 */
class RevenueEngineMaintenanceCancelTest {

    private val day = 86_400_000L
    private val start = 1_780_000_000_000L        // arbitrary fixed instant
    private val perDay = BigDecimal("300")

    private fun rental(
        status: String,
        reason: String? = null,
        cancelledAt: Long? = null,
        num: Int = 10,
    ) = RevenueEngine.Rental(
        status = status,
        startMillis = start,
        numDays = num,
        totalPrice = perDay.multiply(BigDecimal(num)),
        cancellationReason = reason,
        cancelledAtMillis = cancelledAt,
        endMillis = start + num * day,
    )

    // whole-year window in epoch-days around `start`
    private val fromDay = RevenueEngine.bizEpochDay(start) - 400
    private val toDay = RevenueEngine.bizEpochDay(start) + 400

    @Test
    fun `maintenance-cancelled rental realises only elapsed days`() {
        val r = rental("CANCELLED", reason = "MAINTENANCE", cancelledAt = start + 3 * day)
        // interrupted on day 3 -> 4 realised day-slices (day0..day3) @ 300 = 1200
        val now = start + 5 * day
        assertEquals(1200.0, RevenueEngine.revenueBetween(listOf(r), fromDay, toDay, now), 0.001)
    }

    @Test
    fun `maintenance-cancelled revenue does not grow after the original end`() {
        val r = rental("CANCELLED", reason = "MAINTENANCE", cancelledAt = start + 3 * day)
        val early = RevenueEngine.revenueBetween(listOf(r), fromDay, toDay, start + 5 * day)
        val late = RevenueEngine.revenueBetween(listOf(r), fromDay, toDay, start + 100 * day)
        assertEquals("interrupted-rental revenue must be stable over time", early, late, 0.001)
        assertEquals(1200.0, late, 0.001)
    }

    @Test
    fun `plain manual cancellation contributes zero`() {
        val r = rental("CANCELLED", reason = null, cancelledAt = start + 3 * day)
        assertEquals(0.0, RevenueEngine.revenueBetween(listOf(r), fromDay, toDay, start + 100 * day), 0.001)
    }
}
