package com.example.data.fleet

import java.text.SimpleDateFormat
import java.util.Calendar
import java.util.Date
import java.util.Locale
import java.util.TimeZone

/**
 * Kotlin adapter of the NORMATIVE fleet-status specification
 * (`shared/fleet_status_reference.py` + `shared/fleet_status_cases.json`) —
 * the mobile mirror of `desktop/app/utils/fleet_status.py` and
 * `backend/app/services/fleet_status.py`.
 *
 * This file re-implements NO business rule of its own: it is a mechanical port
 * of the shared reference, and `FleetStatusParityTest` drives it with the
 * shared cross-runtime vectors so it can never drift from Desktop/Backend.
 *
 * PRECEDENCE (mutually exclusive):
 *   SOLD / INACTIVE  (structural) > MAINTENANCE > RENTED > RESERVED > AVAILABLE
 *
 * RENTED is time-derived: a blocking reservation (RESERVED or ACTIVE) whose
 * window contains `now` means the car is physically out (no separate pickup
 * step). RESERVED means a blocking reservation is still UPCOMING (`now < start`).
 *
 * INTERVAL RULE: half-open [start, end). Occupied for `start <= now < end`;
 * exactly at `end` the vehicle is free again.
 *
 * All time is epoch-milliseconds UTC (the codebase's existing convention —
 * `System.currentTimeMillis()` / `SimpleDateFormat` with an explicit TZ — so
 * no `java.time` / desugaring dependency is added). Naive ISO strings are
 * interpreted as UTC, matching `parse_datetime_utc`.
 */
object FleetStatus {

    const val AVAILABLE = "AVAILABLE"
    const val RESERVED = "RESERVED"
    const val RENTED = "RENTED"
    const val MAINTENANCE = "MAINTENANCE"

    val CASABLANCA: TimeZone = TimeZone.getTimeZone("Africa/Casablanca")

    private val STRUCTURAL = setOf("SOLD", "INACTIVE")
    private val TERMINAL_MAINTENANCE = setOf("COMPLETED", "CANCELLED")
    private val BLOCKING_RESERVATION = setOf("ACTIVE", "RESERVED")
    private const val FAR_FUTURE = Long.MAX_VALUE

    data class VehicleRow(val id: String, val status: String?)
    data class ReservationRow(
        val vehicleId: String,
        val status: String?,
        val startIso: String?,
        val endIso: String?,
        val totalAmount: Double = 0.0,
    )

    data class MaintenanceRow(
        val vehicleId: String,
        val status: String?,
        val startIso: String?,
        val expectedEndIso: String?,
        val actualEndIso: String?,
    )

    // ── canonical parser (mirror of parse_datetime_utc) ────────────────────
    private val ISO_FORMATS = listOf(
        "yyyy-MM-dd'T'HH:mm:ssXXX",   // explicit offset
        "yyyy-MM-dd'T'HH:mm:ss",      // naive -> UTC
        "yyyy-MM-dd HH:mm:ss",        // SQLite
        "yyyy-MM-dd'T'HH:mm",
        "yyyy-MM-dd",
    )

    fun parseUtcMillis(value: String?): Long? {
        if (value.isNullOrBlank()) return null
        var s = value.trim().replace("z", "Z")
        // normalise "...Z" to "...+00:00" so XXX can parse it
        if (s.endsWith("Z")) s = s.dropLast(1) + "+00:00"
        // drop fractional seconds: "12:00:00.123456+00:00" -> "12:00:00+00:00"
        val dot = s.indexOf('.')
        if (dot >= 0) {
            var j = dot + 1
            while (j < s.length && s[j].isDigit()) j++
            s = s.substring(0, dot) + s.substring(j)
        }
        for (fmt in ISO_FORMATS) {
            try {
                val sdf = SimpleDateFormat(fmt, Locale.US)
                sdf.isLenient = false
                if (!fmt.contains("XXX")) sdf.timeZone = TimeZone.getTimeZone("UTC")
                return sdf.parse(s)?.time
            } catch (_: Exception) {
            }
        }
        return null
    }

    private fun norm(s: String?): String = (s ?: "").trim().uppercase(Locale.US)

    private fun maintenanceEndMillis(m: MaintenanceRow): Long =
        parseUtcMillis(m.actualEndIso) ?: parseUtcMillis(m.expectedEndIso) ?: FAR_FUTURE

    // ── effective status ─────────────────────────────────────────────────
    fun effectiveStatuses(
        vehicles: List<VehicleRow>,
        reservations: List<ReservationRow>,
        maintenances: List<MaintenanceRow>,
        nowMillis: Long,
    ): Map<String, String> {
        val result = LinkedHashMap<String, String>()
        val structural = HashSet<String>()
        for (v in vehicles) {
            val st = norm(v.status)
            if (st in STRUCTURAL) {
                result[v.id] = st
                structural.add(v.id)
            } else {
                result[v.id] = AVAILABLE
            }
        }

        val maintVids = HashSet<String>()
        for (m in maintenances) {
            if (m.vehicleId in structural || m.vehicleId !in result) continue
            if (norm(m.status) in TERMINAL_MAINTENANCE) continue
            val start = parseUtcMillis(m.startIso) ?: continue
            if (start <= nowMillis && nowMillis < maintenanceEndMillis(m)) {
                maintVids.add(m.vehicleId)
            }
        }

        val rentedVids = HashSet<String>()
        val reservedVids = HashSet<String>()
        for (r in reservations) {
            if (r.vehicleId in structural || r.vehicleId in maintVids || r.vehicleId !in result) continue
            val st = norm(r.status)
            if (st !in BLOCKING_RESERVATION) continue
            val start = parseUtcMillis(r.startIso) ?: continue
            val end = parseUtcMillis(r.endIso) ?: continue
            if (start <= nowMillis && nowMillis < end) {
                // Window contains now -> car is out (no separate pickup step).
                rentedVids.add(r.vehicleId)
            } else if (nowMillis < start) {
                // Upcoming booking -> surfaced as RESERVED.
                reservedVids.add(r.vehicleId)
            }
        }
        reservedVids.removeAll(rentedVids)

        for (id in result.keys.toList()) {
            if (id in structural) continue
            result[id] = when (id) {
                in maintVids -> MAINTENANCE
                in rentedVids -> RENTED
                in reservedVids -> RESERVED
                else -> AVAILABLE
            }
        }
        return result
    }

    fun fleetCounts(
        vehicles: List<VehicleRow>,
        reservations: List<ReservationRow>,
        maintenances: List<MaintenanceRow>,
        nowMillis: Long,
    ): Map<String, Int> {
        val statuses = effectiveStatuses(vehicles, reservations, maintenances, nowMillis)
        var available = 0; var reserved = 0; var rented = 0; var maintenance = 0
        for (s in statuses.values) when (s) {
            AVAILABLE -> available++
            RESERVED -> reserved++
            RENTED -> rented++
            MAINTENANCE -> maintenance++
        }
        val total = available + reserved + rented + maintenance
        return mapOf(
            "total_vehicles" to total,
            "available" to available,
            "reserved" to reserved,
            "rented" to rented,
            "maintenance" to maintenance,
        )
    }

    // ── next temporal boundary ───────────────────────────────────────────
    /**
     * Earliest FUTURE instant (strictly `> nowMillis`) at which some vehicle's
     * effective status could change purely because time advanced — the
     * reservation / maintenance interval edges, and (when [includeMidnight])
     * the next local-midnight in [zone] for dashboard period rollover.
     * Returns null when nothing is pending.
     */
    fun nextBoundaryMillis(
        reservations: List<ReservationRow>,
        maintenances: List<MaintenanceRow>,
        nowMillis: Long,
        includeMidnight: Boolean = false,
        zone: TimeZone = CASABLANCA,
    ): Long? {
        var best: Long? = null
        fun consider(t: Long?) {
            if (t != null && t > nowMillis && (best == null || t < best!!)) best = t
        }

        for (r in reservations) {
            if (norm(r.status) !in BLOCKING_RESERVATION) continue
            consider(parseUtcMillis(r.startIso))
            consider(parseUtcMillis(r.endIso))
        }
        for (m in maintenances) {
            if (norm(m.status) in TERMINAL_MAINTENANCE) continue
            consider(parseUtcMillis(m.startIso))
            val end = maintenanceEndMillis(m)
            if (end != FAR_FUTURE) consider(end)
        }
        if (includeMidnight) consider(nextMidnightMillis(nowMillis, zone))
        return best
    }

    // ── dashboard period overview (mirror of dashboard_cache.compute_overview_rows) ──
    data class PeriodOverview(
        val totalVehicles: Int, val available: Int, val rented: Int,
        val reserved: Int, val maintenance: Int,
        val todayBookings: Int, val weekBookings: Int, val monthBookings: Int,
        val todayRevenue: Double, val weekRevenue: Double, val monthRevenue: Double,
    )

    /** Africa/Casablanca-local [today, tomorrow), [weekStart Mon, +7d),
     *  [monthStart, nextMonth) as epoch-millis bounds for [nowMillis]. */
    private fun periodBounds(nowMillis: Long, zone: TimeZone): Triple<LongRange, LongRange, LongRange> {
        fun cal() = Calendar.getInstance(zone, Locale.US).apply {
            firstDayOfWeek = Calendar.MONDAY; time = Date(nowMillis)
            set(Calendar.HOUR_OF_DAY, 0); set(Calendar.MINUTE, 0)
            set(Calendar.SECOND, 0); set(Calendar.MILLISECOND, 0)
        }
        val todayStart = cal().timeInMillis
        val todayEnd = cal().apply { add(Calendar.DAY_OF_YEAR, 1) }.timeInMillis
        val weekStart = cal().apply {
            val dow = (get(Calendar.DAY_OF_WEEK) + 5) % 7   // Mon=0..Sun=6
            add(Calendar.DAY_OF_YEAR, -dow)
        }.timeInMillis
        val weekEnd = weekStart + 7L * 86_400_000L
        val monthStart = cal().apply { set(Calendar.DAY_OF_MONTH, 1) }.timeInMillis
        val monthEnd = cal().apply { set(Calendar.DAY_OF_MONTH, 1); add(Calendar.MONTH, 1) }.timeInMillis
        return Triple(todayStart until todayEnd, weekStart until weekEnd, monthStart until monthEnd)
    }

    fun dashboardOverview(
        vehicles: List<VehicleRow>,
        reservations: List<ReservationRow>,
        maintenances: List<MaintenanceRow>,
        nowMillis: Long,
        zone: TimeZone = CASABLANCA,
    ): PeriodOverview {
        val counts = fleetCounts(vehicles, reservations, maintenances, nowMillis)
        val (today, week, month) = periodBounds(nowMillis, zone)
        var tB = 0; var wB = 0; var mB = 0
        var tR = 0.0; var wR = 0.0; var mR = 0.0
        for (r in reservations) {
            val st = norm(r.status)
            if (st == "CANCELLED") continue
            val start = parseUtcMillis(r.startIso) ?: continue
            val inT = start in today; val inW = start in week; val inM = start in month
            if (inT) tB++; if (inW) wB++; if (inM) mB++
            // Revenue is recognised when the rental has started (start <= now):
            // any non-cancelled booking whose window has begun.
            if (start <= nowMillis) {
                if (inT) tR += r.totalAmount; if (inW) wR += r.totalAmount; if (inM) mR += r.totalAmount
            }
        }
        return PeriodOverview(
            counts["total_vehicles"]!!, counts["available"]!!, counts["rented"]!!,
            counts["reserved"]!!, counts["maintenance"]!!,
            tB, wB, mB, tR, wR, mR,
        )
    }

    /** The next local midnight in [zone] strictly after [nowMillis]. */
    fun nextMidnightMillis(nowMillis: Long, zone: TimeZone = CASABLANCA): Long {
        val cal = Calendar.getInstance(zone, Locale.US)
        cal.time = Date(nowMillis)
        cal.add(Calendar.DAY_OF_YEAR, 1)
        cal.set(Calendar.HOUR_OF_DAY, 0)
        cal.set(Calendar.MINUTE, 0)
        cal.set(Calendar.SECOND, 0)
        cal.set(Calendar.MILLISECOND, 0)
        return cal.timeInMillis
    }
}
