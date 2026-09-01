package com.example

import com.example.data.fleet.FleetStatus
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import java.io.File

/**
 * Increment 5 — CROSS-CLIENT LIVE CONVERGENCE.
 *
 * The same authoritative fixture (`shared/fleet_status_cases.json`) drives
 * Backend (`test_fleet_status_crossruntime.py`), Desktop A/B
 * (`test_cross_client_convergence.py`) and — here — Mobile. For identical
 * interval data every client must derive the SAME:
 *
 *   - effective vehicle statuses
 *   - fleet counts / dashboard overview buckets
 *   - next temporal boundary
 *
 * No client may invent its own result. `expected_next_boundary` in the shared
 * vectors is `fleet_status_reference.next_boundary(...)`; the Python parity
 * tests guard it against drift from the reference, this test asserts the
 * Kotlin runtime reproduces it.
 */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [36])
class CrossClientConvergenceTest {

    private fun casesFile(): File {
        var dir: File? = File(System.getProperty("user.dir") ?: ".").absoluteFile
        repeat(8) {
            val d = dir ?: return@repeat
            val candidate = File(d, "shared/fleet_status_cases.json")
            if (candidate.isFile) return candidate
            dir = d.parentFile
        }
        throw IllegalStateException("shared/fleet_status_cases.json not found")
    }

    private fun JSONObject.strOrNull(k: String): String? =
        if (!has(k) || isNull(k)) null else getString(k)

    @Test
    fun `mobile converges with backend and desktop on every shared vector`() {
        val root = JSONObject(casesFile().readText())
        val now = FleetStatus.parseUtcMillis(root.getString("now"))!!
        val cases = root.getJSONArray("cases")
        var checked = 0

        for (i in 0 until cases.length()) {
            val c = cases.getJSONObject(i)
            val name = c.getString("name")

            val vehicles = c.getJSONArray("vehicles").let { arr ->
                (0 until arr.length()).map {
                    val v = arr.getJSONObject(it)
                    FleetStatus.VehicleRow(v.getString("id"), v.strOrNull("status"))
                }
            }
            val reservations = c.getJSONArray("reservations").let { arr ->
                (0 until arr.length()).map {
                    val r = arr.getJSONObject(it)
                    FleetStatus.ReservationRow(
                        r.getString("vehicle_id"), r.strOrNull("status"),
                        r.strOrNull("start"), r.strOrNull("end"),
                    )
                }
            }
            val maintenances = c.getJSONArray("maintenances").let { arr ->
                (0 until arr.length()).map {
                    val m = arr.getJSONObject(it)
                    FleetStatus.MaintenanceRow(
                        m.getString("vehicle_id"), m.strOrNull("status"), m.strOrNull("start"),
                        m.strOrNull("expected_end"), m.strOrNull("actual_end"),
                    )
                }
            }

            // effective status
            val expectedEff = c.getJSONObject("expected_effective").let { o ->
                o.keys().asSequence().associateWith { o.getString(it) }
            }
            assertEquals("$name: effective status", expectedEff,
                FleetStatus.effectiveStatuses(vehicles, reservations, maintenances, now))

            // fleet counts + dashboard overview buckets (same numbers a client
            // shows on the dashboard) — must agree with the shared expectation.
            val expectedCounts = c.getJSONObject("expected_counts").let { o ->
                o.keys().asSequence().associateWith { o.getInt(it) }
            }
            val counts = FleetStatus.fleetCounts(vehicles, reservations, maintenances, now)
            val overview = FleetStatus.dashboardOverview(vehicles, reservations, maintenances, now)
            for ((k, v) in expectedCounts) {
                assertEquals("$name: fleetCounts '$k'", v, counts[k])
            }
            assertEquals("$name: overview available", expectedCounts["available"], overview.available)
            assertEquals("$name: overview rented", expectedCounts["rented"], overview.rented)
            assertEquals("$name: overview reserved", expectedCounts["reserved"], overview.reserved)
            assertEquals("$name: overview maintenance", expectedCounts["maintenance"], overview.maintenance)
            assertEquals("$name: overview total", expectedCounts["total_vehicles"], overview.totalVehicles)

            // next temporal boundary (no midnight injection — matches the ref)
            val expectedNb = c.strOrNull("expected_next_boundary")?.let { FleetStatus.parseUtcMillis(it) }
            val gotNb = FleetStatus.nextBoundaryMillis(reservations, maintenances, now, includeMidnight = false)
            assertEquals("$name: next boundary", expectedNb, gotNb)

            checked++
        }
        assertTrue(checked >= 14)
    }
}
