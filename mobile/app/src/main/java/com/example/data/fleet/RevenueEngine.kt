package com.example.data.fleet

import java.math.BigDecimal
import java.math.RoundingMode
import java.util.Calendar
import java.util.Locale
import java.util.TimeZone
import kotlin.math.floor

/**
 * Mobile port of the normative revenue spec `shared/revenue_reference.py`
 * (PRO-RATA BY DAY). Byte-for-byte parity is enforced by
 * `RevenueEngineParityTest` against `shared/revenue_cases.json` — the same
 * fixture the backend and desktop revenue engines assert against, so the
 * three runtimes can never show a different chiffre d'affaires.
 *
 * Rule: a rental of `numDays` days starting at instant S is made of day-slices
 * day_i = [S + i days, S + (i+1) days); day_i is booked against calendar date
 * date(S)+i and earns totalPrice/numDays. day_i is REALISED once now >= S + i
 * days. Revenue of window [fromDate, toDate) (to EXCLUSIVE) = sum over every
 * non-CANCELLED reservation of its per-day rate times the count of its
 * realised days whose calendar date is in the window.
 */
object RevenueEngine {

    val BUSINESS_TZ: TimeZone = TimeZone.getTimeZone("Africa/Casablanca")

    /** A reservation as the engine needs it. */
    data class Rental(
        val status: String?,
        val startMillis: Long?,
        val numDays: Int,
        val totalPrice: BigDecimal?,
        val dailyPrice: BigDecimal? = null,
        /** Machine cause when status == CANCELLED (e.g. "MAINTENANCE"). */
        val cancellationReason: String? = null,
        /** Instant the rental was cancelled — caps realised days for a rental
         *  interrupted after it started. Falls back to endMillis for legacy rows. */
        val cancelledAtMillis: Long? = null,
        val endMillis: Long? = null,
    )

    /** Mirror of shared.revenue_reference.is_revenue_eligible. */
    private fun isRevenueEligible(r: Rental): Boolean {
        val s = (r.status ?: "").trim().uppercase(Locale.US)
        if (s.isEmpty()) return false
        if (s == "CANCELLED") {
            return (r.cancellationReason ?: "").trim().uppercase(Locale.US) == "MAINTENANCE"
        }
        return true
    }

    /** Epoch-day (days since 1970-01-01) of the business-local calendar date a
     *  moment falls on. Uses the "UTC midnight of that Y/M/D" trick so the
     *  result is a clean integer independent of the zone offset. */
    fun bizEpochDay(millis: Long, zone: TimeZone = BUSINESS_TZ): Long {
        val c = Calendar.getInstance(zone, Locale.US).apply { timeInMillis = millis }
        return epochDayOf(c.get(Calendar.YEAR), c.get(Calendar.MONTH), c.get(Calendar.DAY_OF_MONTH))
    }

    /** Epoch-day of an ISO `yyyy-MM-dd` date string. */
    fun epochDayOfIso(iso: String): Long {
        val p = iso.trim().split("-")
        return epochDayOf(p[0].toInt(), p[1].toInt() - 1, p[2].toInt())
    }

    private fun epochDayOf(year: Int, month0: Int, day: Int): Long {
        val u = Calendar.getInstance(TimeZone.getTimeZone("UTC"), Locale.US).apply {
            clear(); set(year, month0, day, 0, 0, 0)
        }
        return Math.floorDiv(u.timeInMillis, 86_400_000L)
    }

    private fun realisedDays(startMillis: Long, numDays: Int, nowMillis: Long): Int {
        val elapsed = (nowMillis - startMillis).toDouble() / 86_400_000.0
        val n = floor(elapsed).toInt() + 1
        return n.coerceIn(0, numDays)
    }

    private fun perDay(r: Rental): BigDecimal {
        val tp = r.totalPrice
        return if (tp != null && r.numDays > 0) {
            tp.divide(BigDecimal(r.numDays), 12, RoundingMode.HALF_UP)
        } else {
            r.dailyPrice ?: BigDecimal.ZERO
        }
    }

    /** Realised pro-rata revenue for [fromEpochDay, toEpochDay) (to exclusive). */
    fun revenueBetween(
        rentals: List<Rental>,
        fromEpochDay: Long,
        toEpochDay: Long,
        nowMillis: Long,
        zone: TimeZone = BUSINESS_TZ,
    ): Double {
        var acc = BigDecimal.ZERO
        for (r in rentals) {
            acc = acc.add(reservationRevenue(r, fromEpochDay, toEpochDay, nowMillis, zone))
        }
        return acc.setScale(2, RoundingMode.HALF_UP).toDouble()
    }

    fun rentalDaysBetween(
        rentals: List<Rental>,
        fromEpochDay: Long,
        toEpochDay: Long,
        nowMillis: Long,
        zone: TimeZone = BUSINESS_TZ,
    ): Int {
        var total = 0
        for (r in rentals) {
            total += realisedWindowDays(r, fromEpochDay, toEpochDay, nowMillis, zone)
        }
        return total
    }

    private fun realisedWindowDays(
        r: Rental, fromEpochDay: Long, toEpochDay: Long, nowMillis: Long, zone: TimeZone,
    ): Int {
        val status = (r.status ?: "").trim().uppercase(Locale.US)
        if (!isRevenueEligible(r)) return 0
        if (r.numDays <= 0 || r.startMillis == null) return 0
        val reason = (r.cancellationReason ?: "").trim().uppercase(Locale.US)
        val realised = if (status == "CANCELLED" && reason == "MAINTENANCE") {
            // Interrupted rental: only days realised BEFORE the interruption,
            // and that number never grows afterwards. Cap the clock at
            // cancelledAt (fall back to endMillis for legacy rows).
            val cap = r.cancelledAtMillis ?: r.endMillis
            val effectiveNow = if (cap != null) minOf(nowMillis, cap) else nowMillis
            realisedDays(r.startMillis, r.numDays, effectiveNow)
        } else if (status == "COMPLETED") {
            r.numDays
        } else {
            realisedDays(r.startMillis, r.numDays, nowMillis)
        }
        if (realised <= 0) return 0
        val startDay = bizEpochDay(r.startMillis, zone)
        val lo = maxOf(startDay, fromEpochDay)
        val hi = minOf(startDay + realised, toEpochDay)
        return (hi - lo).coerceAtLeast(0L).toInt()
    }

    private fun reservationRevenue(
        r: Rental, fromEpochDay: Long, toEpochDay: Long, nowMillis: Long, zone: TimeZone,
    ): BigDecimal {
        val days = realisedWindowDays(r, fromEpochDay, toEpochDay, nowMillis, zone)
        if (days <= 0) return BigDecimal.ZERO
        return perDay(r).multiply(BigDecimal(days))
    }

    // ── named reporting periods (mirror shared.money_time.period_bounds) ──
    /** (fromEpochDay, toEpochDay) — to EXCLUSIVE — for a preset name. */
    fun namedPeriodBounds(name: String, nowMillis: Long, zone: TimeZone = BUSINESS_TZ): Pair<Long, Long> {
        fun cal() = Calendar.getInstance(zone, Locale.US).apply {
            firstDayOfWeek = Calendar.MONDAY
            timeInMillis = nowMillis
            set(Calendar.HOUR_OF_DAY, 0); set(Calendar.MINUTE, 0)
            set(Calendar.SECOND, 0); set(Calendar.MILLISECOND, 0)
        }
        fun day(c: Calendar) = epochDayOf(c.get(Calendar.YEAR), c.get(Calendar.MONTH), c.get(Calendar.DAY_OF_MONTH))
        val today = day(cal())
        return when (name) {
            "today" -> today to today + 1
            "yesterday" -> today - 1 to today
            "week" -> {
                val c = cal(); val dow = (c.get(Calendar.DAY_OF_WEEK) + 5) % 7
                val s = day(cal().apply { add(Calendar.DAY_OF_YEAR, -dow) })
                s to s + 7
            }
            "last_week" -> {
                val c = cal(); val dow = (c.get(Calendar.DAY_OF_WEEK) + 5) % 7
                val tw = day(cal().apply { add(Calendar.DAY_OF_YEAR, -dow) })
                tw - 7 to tw
            }
            "month" -> {
                val s = day(cal().apply { set(Calendar.DAY_OF_MONTH, 1) })
                val e = day(cal().apply { set(Calendar.DAY_OF_MONTH, 1); add(Calendar.MONTH, 1) })
                s to e
            }
            "last_month" -> {
                val e = day(cal().apply { set(Calendar.DAY_OF_MONTH, 1) })
                val s = day(cal().apply { set(Calendar.DAY_OF_MONTH, 1); add(Calendar.MONTH, -1) })
                s to e
            }
            "year" -> {
                val s = day(cal().apply { set(Calendar.MONTH, 0); set(Calendar.DAY_OF_MONTH, 1) })
                val e = day(cal().apply { set(Calendar.MONTH, 0); set(Calendar.DAY_OF_MONTH, 1); add(Calendar.YEAR, 1) })
                s to e
            }
            "last_year" -> {
                val e = day(cal().apply { set(Calendar.MONTH, 0); set(Calendar.DAY_OF_MONTH, 1) })
                val s = day(cal().apply { set(Calendar.MONTH, 0); set(Calendar.DAY_OF_MONTH, 1); add(Calendar.YEAR, -1) })
                s to e
            }
            else -> throw IllegalArgumentException("unknown period: $name")
        }
    }

    /** Inclusive UI 'Au' date -> exclusive toEpochDay. */
    fun customBounds(fromIso: String, toIsoInclusive: String): Pair<Long, Long> {
        var a = epochDayOfIso(fromIso)
        var b = epochDayOfIso(toIsoInclusive)
        if (b < a) { val t = a; a = b; b = t }
        return a to b + 1
    }
}
