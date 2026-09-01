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
 * CROSS-RUNTIME PARITY — mobile vs the normative spec.
 *
 * Drives `FleetStatus` (the mobile port) with the exact same vector set as
 * `backend/tests/test_fleet_status_crossruntime.py` and
 * `desktop/tests/test_fleet_status_crossruntime.py`
 * (`shared/fleet_status_cases.json`). If the mobile derivation drifts from
 * Desktop / Backend / the reference, this fails.
 */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [36])
class FleetStatusParityTest {

    private fun casesFile(): File {
        var dir: File? = File(System.getProperty("user.dir") ?: ".").absoluteFile
        repeat(8) {
            val d = dir ?: return@repeat
            val candidate = File(d, "shared/fleet_status_cases.json")
            if (candidate.isFile) return candidate
            dir = d.parentFile
        }
        throw IllegalStateException("shared/fleet_status_cases.json not found from ${System.getProperty("user.dir")}")
    }

    private fun millis(iso: String): Long =
        FleetStatus.parseUtcMillis(iso) ?: error("bad now: $iso")

    @Test
    fun `mobile fleet status matches the shared normative vectors`() {
        val root = JSONObject(casesFile().readText())
        val now = millis(root.getString("now"))
        val cases = root.getJSONArray("cases")

        var checked = 0
        for (i in 0 until cases.length()) {
            val c = cases.getJSONObject(i)
            val name = c.getString("name")
            fun JSONObject.str(k: String): String? = if (isNull(k) || !has(k)) null else getString(k)

            val vehicles = c.getJSONArray("vehicles").let { arr ->
                (0 until arr.length()).map {
                    val v = arr.getJSONObject(it)
                    FleetStatus.VehicleRow(v.getString("id"), v.str("status"))
                }
            }
            val reservations = c.getJSONArray("reservations").let { arr ->
                (0 until arr.length()).map {
                    val r = arr.getJSONObject(it)
                    FleetStatus.ReservationRow(
                        r.getString("vehicle_id"), r.str("status"), r.str("start"), r.str("end"),
                    )
                }
            }
            val maintenances = c.getJSONArray("maintenances").let { arr ->
                (0 until arr.length()).map {
                    val m = arr.getJSONObject(it)
                    FleetStatus.MaintenanceRow(
                        m.getString("vehicle_id"), m.str("status"), m.str("start"),
                        m.str("expected_end"), m.str("actual_end"),
                    )
                }
            }

            val expectedEff = c.getJSONObject("expected_effective").let { o ->
                o.keys().asSequence().associateWith { o.getString(it) }
            }
            val expectedCounts = c.getJSONObject("expected_counts").let { o ->
                o.keys().asSequence().associateWith { o.getInt(it) }
            }

            val gotEff = FleetStatus.effectiveStatuses(vehicles, reservations, maintenances, now)
            assertEquals("$name: effective status drift", expectedEff, gotEff)

            val gotCounts = FleetStatus.fleetCounts(vehicles, reservations, maintenances, now)
            for ((k, v) in expectedCounts) {
                assertEquals("$name: count '$k' drift", v, gotCounts[k])
            }
            checked++
        }
        assertTrue("expected to run the shared vectors", checked >= 10)
    }
}
