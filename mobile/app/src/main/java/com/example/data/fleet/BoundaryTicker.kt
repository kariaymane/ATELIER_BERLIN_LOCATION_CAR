package com.example.data.fleet

import kotlinx.coroutines.channels.awaitClose
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.channelFlow
import kotlinx.coroutines.flow.collectLatest
import kotlinx.coroutines.isActive

/**
 * The ONE mobile temporal mechanism — the phone's equivalent of the desktop
 * `BoundaryClock`. It is NOT a per-screen timer and NOT a poller: it sleeps
 * exactly until the next reservation / maintenance / local-midnight boundary
 * and emits a tick, so a `combine(...)` over the Room flows re-derives the
 * effective fleet status and Compose recomposes — with no API call, no Room
 * write, no navigation, no user action.
 *
 * Lifecycle / concurrency guarantees (all from structured concurrency, not
 * hand-rolled bookkeeping):
 *  - the returned Flow is cold; it runs only while collected (the ViewModel
 *    collects it inside `viewModelScope` with `WhileSubscribed`), so it stops
 *    with the screen and leaks nothing;
 *  - `collectLatest` on the interval data means a sync / mutation that changes
 *    the rows CANCELS the pending wait and restarts against the fresh data —
 *    one active schedule at a time, obsolete boundary invalidated;
 *  - `delayFn` and `nowMillis` are injectable for deterministic virtual-time
 *    tests.
 */
class BoundaryTicker(
    private val nowMillis: () -> Long = { System.currentTimeMillis() },
    private val delayFn: suspend (Long) -> Unit = { ms -> delay(ms) },
    private val includeMidnight: Boolean = true,
) {
    fun ticks(
        intervals: Flow<Pair<List<FleetStatus.ReservationRow>, List<FleetStatus.MaintenanceRow>>>,
    ): Flow<Long> = channelFlow {
        trySend(nowMillis())  // prime immediately so combine() can start
        intervals.collectLatest { (reservations, maintenances) ->
            while (currentCoroutineContext().isActive) {
                val now = nowMillis()
                val boundary = FleetStatus.nextBoundaryMillis(
                    reservations, maintenances, now, includeMidnight,
                ) ?: break  // nothing pending — sleep until the data changes
                delayFn((boundary - now).coerceAtLeast(0L))
                trySend(nowMillis())
                // loop: recompute the next boundary against the advanced `now`
                // (the edge we just serviced is now in the past and excluded)
            }
        }
        awaitClose { }
    }
}
