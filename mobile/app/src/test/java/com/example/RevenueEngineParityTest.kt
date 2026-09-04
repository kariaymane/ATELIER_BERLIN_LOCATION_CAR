package com.example

import com.example.data.fleet.RevenueEngine
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import java.io.File
import java.math.BigDecimal
import java.text.SimpleDateFormat
import java.util.Locale
import java.util.TimeZone

/**
 * CROSS-RUNTIME PARITY — mobile RevenueEngine vs the normative spec.
 *
 * Drives the mobile pro-rata engine with the exact same vector set as
 * backend/tests/test_revenue_crossruntime.py and
 * desktop/tests/test_dashboard_cache_parity.py (shared/revenue_cases.json).
 * If the mobile revenue math drifts from Desktop / Backend / the reference,
 * this fails — "the two apps show a different CA" becomes a red build.
 */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [36])
class RevenueEngineParityTest {

    private fun casesFile(): File {
        var dir: File? = File(System.getProperty("user.dir") ?: ".").absoluteFile
        repeat(8) {
            val d = dir ?: return@repeat
            val c = File(d, "shared/revenue_cases.json")
            if (c.isFile) return c
            dir = d.parentFile
        }
        throw IllegalStateException("shared/revenue_cases.json not found")
    }

    private fun millis(iso: String): Long {
        var s = iso.trim()
        if (s.endsWith("Z")) s = s.dropLast(1) + "+00:00"
        val dot = s.indexOf('.')
        if (dot >= 0) {
            var j = dot + 1; while (j < s.length && s[j].isDigit()) j++
            s = s.substring(0, dot) + s.substring(j)
        }
        return SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ssXXX", Locale.US).parse(s)!!.time
    }

    @Test
    fun `mobile revenue matches the shared normative vectors`() {
        val root = JSONObject(casesFile().readText())
        val cases = root.getJSONArray("revenue_cases")
        var checked = 0
        for (i in 0 until cases.length()) {
            val c = cases.getJSONObject(i)
            val name = c.getString("name")
            val now = millis(c.getString("now"))
            val rentals = c.getJSONArray("reservations").let { arr ->
                (0 until arr.length()).map {
                    val r = arr.getJSONObject(it)
                    RevenueEngine.Rental(
                        status = r.getString("status"),
                        startMillis = millis(r.getString("start_datetime")),
                        numDays = r.getInt("num_days"),
                        totalPrice = BigDecimal(r.getString("total_price")),
                        cancellationReason = r.optString("cancellation_reason", null),
                        cancelledAtMillis = r.optString("cancelled_at", null)?.let { s -> millis(s) },
                        endMillis = r.optString("end_datetime", null)?.let { s -> millis(s) },
                    )
                }
            }
            val queries = c.getJSONArray("queries")
            for (q in 0 until queries.length()) {
                val query = queries.getJSONObject(q)
                val from = RevenueEngine.epochDayOfIso(query.getString("from"))
                val to = RevenueEngine.epochDayOfIso(query.getString("to"))
                val gotRev = RevenueEngine.revenueBetween(rentals, from, to, now)
                val gotDays = RevenueEngine.rentalDaysBetween(rentals, from, to, now)
                assertEquals(
                    "$name ${query.getString("from")}..${query.getString("to")} revenue",
                    query.getDouble("expected_revenue"), gotRev, 0.001,
                )
                assertEquals(
                    "$name ${query.getString("from")}..${query.getString("to")} days",
                    query.getInt("expected_days"), gotDays,
                )
                checked++
            }
        }
        assert(checked >= 20) { "expected >= 20 revenue vectors, ran $checked" }
    }

    @Test
    fun `named period bounds match the shared vectors`() {
        val root = JSONObject(casesFile().readText())
        val cases = root.getJSONArray("period_bounds_cases")
        for (i in 0 until cases.length()) {
            val c = cases.getJSONObject(i)
            val now = millis(c.getString("now"))
            val (from, to) = RevenueEngine.namedPeriodBounds(c.getString("name"), now)
            assertEquals("${c.getString("name")} from",
                RevenueEngine.epochDayOfIso(c.getString("start")), from)
            assertEquals("${c.getString("name")} to",
                RevenueEngine.epochDayOfIso(c.getString("end")), to)
        }
    }
}
