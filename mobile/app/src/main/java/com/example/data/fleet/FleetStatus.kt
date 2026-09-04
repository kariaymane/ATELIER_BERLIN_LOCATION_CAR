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
 * no `java.time` / desugaring dependency is added).
 *
 * NAIVE-DATETIME POLICY (the ONE policy, product-wide): an ISO string carrying
 * no offset is BUSINESS-LOCAL wall time (Africa/Casablanca), never UTC. This is
 * the contract written in `shared/money_time.to_business` and mirrored by
 * `shared/fleet_status_reference._parse`, `shared/revenue_reference`,
 * `desktop/app/utils/datetime_utils.parse_datetime_utc` and
 * `backend/app/services/fleet_status`. Reading a naive value as UTC shifted
 * every such row by the Casablanca offset and could put Mobile in a different
 * bucket than Desktop/Backend for the SAME row at the SAME instant; the
 * `naive_*` vectors in `shared/fleet_status_cases.json` pin this down.
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
        val numDays: Int = 1,
        val cancellationReason: String? = null,
        val cancelledAtIso: String? = null,
    )

    data class MaintenanceRow(
        val vehicleId: String,
        val status: String?,
        val startIso: String?,
        val expectedEndIso: String?,
        val actualEndIso: String?,
    )

    // ── canonical parser (mirror of parse_datetime_utc) ────────────────────
    // A format WITHOUT "XXX" has no offset in the text, so the parser's own
    // timeZone decides the instant: that is the naive case, and it resolves to
    // BUSINESS_TZ (see the class docstring), not UTC.
    private val ISO_FORMATS = listOf(
        "yyyy-MM-dd'T'HH:mm:ssXXX",   // explicit offset -> as written
        "yyyy-MM-dd'T'HH:mm:ss",      // naive -> business-local
        "yyyy-MM-dd HH:mm:ss",        // SQLite round-trip -> business-local
        "yyyy-MM-dd'T'HH:mm",         // naive -> business-local
        "yyyy-MM-dd",                 // naive date -> business-local midnight
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
                // No offset in the pattern => naive => business-local wall time.
                if (!fmt.contains("XXX")) sdf.timeZone = CASABLANCA
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
        val todayBookings: Int, val weekBookings: Int, val monthBookings: Int, val yearBookings: Int,
        val todayRevenue: Double, val weekRevenue: Double, val monthRevenue: Double, val yearRevenue: Double,
    )

    data class PeriodRanges(
        val today: LongRange, val week: LongRange, val month: LongRange, val year: LongRange,
    )

    /** Africa/Casablanca-local [today, tomorrow), [weekStart Mon, +7d),
     *  [monthStart, nextMonth), [yearStart, nextYear) as epoch-millis bounds. */
    private fun periodBounds(nowMillis: Long, zone: TimeZone): PeriodRanges {
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
        val yearStart = cal().apply { set(Calendar.MONTH, Calendar.JANUARY); set(Calendar.DAY_OF_MONTH, 1) }.timeInMillis
        val yearEnd = cal().apply {
            set(Calendar.MONTH, Calendar.JANUARY); set(Calendar.DAY_OF_MONTH, 1); add(Calendar.YEAR, 1)
        }.timeInMillis
        return PeriodRanges(
            todayStart until todayEnd, weekStart until weekEnd,
            monthStart until monthEnd, yearStart until yearEnd,
        )
    }

    fun dashboardOverview(
        vehicles: List<VehicleRow>,
        reservations: List<ReservationRow>,
        maintenances: List<MaintenanceRow>,
        nowMillis: Long,
        zone: TimeZone = CASABLANCA,
    ): PeriodOverview {
        val counts = fleetCounts(vehicles, reservations, maintenances, nowMillis)
        val p = periodBounds(nowMillis, zone)

        // booking COUNT stays anchored to the start date (a rental "made in
        // September" by when it started).
        var tB = 0; var wB = 0; var mB = 0; var yB = 0
        for (r in reservations) {
            // Mirror shared.revenue_reference.rentals_started_between: a
            // maintenance-interrupted rental still "started" and still counts;
            // any other CANCELLED does not.
            if (norm(r.status) == "CANCELLED" && norm(r.cancellationReason) != "MAINTENANCE") continue
            val start = parseUtcMillis(r.startIso) ?: continue
            if (start in p.today) tB++; if (start in p.week) wB++
            if (start in p.month) mB++; if (start in p.year) yB++
        }

        // revenue = the ONE pro-rata engine (shared/revenue_reference.py).
        val rentals = reservations.map {
            RevenueEngine.Rental(
                status = it.status,
                startMillis = parseUtcMillis(it.startIso),
                numDays = it.numDays,
                totalPrice = java.math.BigDecimal(it.totalAmount.toString()),
                cancellationReason = it.cancellationReason,
                cancelledAtMillis = parseUtcMillis(it.cancelledAtIso),
                endMillis = parseUtcMillis(it.endIso),
            )
        }
        fun rev(name: String): Double {
            val (f, t) = RevenueEngine.namedPeriodBounds(name, nowMillis, zone)
            return RevenueEngine.revenueBetween(rentals, f, t, nowMillis, zone)
        }
        return PeriodOverview(
            counts["total_vehicles"]!!, counts["available"]!!, counts["rented"]!!,
            counts["reserved"]!!, counts["maintenance"]!!,
            tB, wB, mB, yB,
            rev("today"), rev("week"), rev("month"), rev("year"),
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
