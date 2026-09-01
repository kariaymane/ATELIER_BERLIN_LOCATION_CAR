package com.example.data.repository

import android.util.Log
import androidx.room.withTransaction
import com.example.data.api.ApiClient
import com.example.data.api.ClientRentalsReportDto
import com.example.data.api.ClientDto
import com.example.data.api.MaintenanceDto
import com.example.data.api.NotificationDto
import com.example.data.api.RentalDto
import com.example.data.api.SyncBootstrapResponseDto
import com.example.data.api.VehicleDto
import com.example.data.api.WebSocketEventDto
import com.example.data.local.*
import com.example.data.model.*
import com.example.data.fleet.BoundaryTicker
import com.example.data.fleet.FleetStatus
import com.example.util.ImageUrlResolver
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.withContext
import java.text.SimpleDateFormat
import java.util.*

/**
 * The server was reached but explicitly reported its database as unavailable
 * (readiness probe / bootstrap returned HTTP 503). This is a TRANSIENT backend
 * condition — never a reason to wipe the local cache or the session.
 */
class DbUnavailableException(message: String) : Exception(message)

class FleetRepository(
    private val apiClient: ApiClient,
    private val database: AppDatabase,
    private val context: android.content.Context,
    /** Injectable clock — the same one the BoundaryTicker uses. Tests pass a
     *  virtual clock; production uses the wall clock. */
    private val nowMillis: () -> Long = { System.currentTimeMillis() },
    /** Injectable delay for deterministic virtual-time tests. */
    tickerDelay: suspend (Long) -> Unit = { ms -> kotlinx.coroutines.delay(ms) },
) {
    // Raw interval rows (machine-parseable ISO), reactive to every Room write.
    private val intervalRowsFlow: Flow<Pair<List<FleetStatus.ReservationRow>, List<FleetStatus.MaintenanceRow>>> =
        combine(
            database.reservationDao().getAllReservations(),
            database.maintenanceDao().getAllTickets(),
        ) { res, maint ->
            res.map {
                FleetStatus.ReservationRow(
                    it.vehicleId, it.status, it.startDatetimeIso, it.endDatetimeIso,
                    it.totalAmount.toDouble(),
                )
            } to maint.map {
                FleetStatus.MaintenanceRow(
                    it.vehicleId, it.status, it.startDatetimeIso,
                    it.expected_end_datetime, it.actual_end_datetime,
                )
            }
        }

    // The ONE mobile temporal mechanism — ticks at each interval / midnight edge.
    private val boundaryTicker = BoundaryTicker(
        nowMillis = nowMillis, delayFn = tickerDelay, includeMidnight = true,
    )
    private val boundaryTicks: Flow<Long> = boundaryTicker.ticks(intervalRowsFlow)

    /**
     * The Fleet screen's vehicles, with the CANONICAL effective status
     * re-derived locally from the reservation / maintenance intervals against
     * `now` — so a reservation ending at 18:00 flips the vehicle to
     * `DISPONIBLE` at 18:00 with no API call, no Room write, no user action.
     * The re-derivation is the shared normative spec (FleetStatus), identical
     * to Desktop and Backend (proven by FleetStatusParityTest).
     */
    val vehiclesFlow: Flow<List<Vehicle>> = combine(
        database.vehicleDao().getAllVehicles(),
        intervalRowsFlow,
        boundaryTicks,
    ) { vEntities, intervals, _tick ->
        deriveEffectiveVehicles(vEntities, intervals.first, intervals.second, nowMillis())
    }.distinctUntilChanged()

    val reservationsFlow: Flow<List<Reservation>> = database.reservationDao().getAllReservations().map { list ->
        list.map { it.toDomain() }
    }

    companion object {
        // sync_metadata keys
        const val META_IS_BOOTSTRAPPED = "is_bootstrapped"
        const val META_CACHE_COMPLETE = "cache_snapshot_complete"
        const val META_SYNCED_THROUGH_REVISION = "synced_through_revision"

        /**
         * PURE — re-derive the canonical effective status of each vehicle from
         * the local interval rows against `now`. Same normative semantics as
         * Desktop / Backend (FleetStatus). A vehicle with no local interval
         * rows keeps the server-provided status.
         *
         * This per-vehicle fallback is only SOUND when the temporal cache is
         * COMPLETE (see `cacheCompleteFlow` / the Increment-5 completeness
         * invariant): a complete snapshot guarantees that "no local interval
         * row for this vehicle" genuinely means "no interval affects it", so
         * keeping the server status is correct. When the cache is not proven
         * complete, `refreshAll()` forces a full bootstrap instead of trusting
         * this path.
         */
        fun deriveEffectiveVehicles(
            vEntities: List<VehicleEntity>,
            resRows: List<FleetStatus.ReservationRow>,
            maintRows: List<FleetStatus.MaintenanceRow>,
            now: Long,
        ): List<Vehicle> {
            val effective = FleetStatus.effectiveStatuses(
                vEntities.map { FleetStatus.VehicleRow(it.id, it.status) },
                resRows, maintRows, now,
            )
            return vEntities.map { e ->
                val domain = e.toDomain()
                val hasIntervals = resRows.any { it.vehicleId == e.id } ||
                    maintRows.any { it.vehicleId == e.id }
                if (hasIntervals) domain.copy(status = VehicleStatus.fromApi(effective[e.id]))
                else domain
            }
        }
    }

    val maintenanceFlow: Flow<List<MaintenanceTicket>> = database.maintenanceDao().getAllTickets().map { list ->
        list.map { it.toDomain() }
    }

    private val _notifications = MutableStateFlow<List<NotificationItem>>(emptyList())
    val notificationsFlow: StateFlow<List<NotificationItem>> = _notifications.asStateFlow()

    private val _liveMetrics = MutableStateFlow<PerformanceMetrics?>(null)

    /**
     * Dashboard metrics recomputed LOCALLY from Room against `now` + the
     * boundary ticker — so the fleet cards AND the period (today/week/month)
     * revenue cards roll over at local midnight with no API call, no user
     * action. Same period formula as `backend/.../dashboard_service` and
     * `desktop/.../dashboard_cache`. Null until vehicles are cached.
     */
    private val localMetricsFlow: Flow<PerformanceMetrics?> = combine(
        database.vehicleDao().getAllVehicles(),
        intervalRowsFlow,
        boundaryTicks,
    ) { vEntities, intervals, _tick ->
        if (vEntities.isEmpty()) return@combine null
        val ov = FleetStatus.dashboardOverview(
            vEntities.map { FleetStatus.VehicleRow(it.id, it.status) },
            intervals.first, intervals.second, nowMillis(),
        )
        PerformanceMetrics(
            todayBookings = ov.todayBookings, weekBookings = ov.weekBookings,
            monthBookings = ov.monthBookings,
            todayRevenue = ov.todayRevenue, weekRevenue = ov.weekRevenue,
            monthRevenue = ov.monthRevenue,
            readyVehicles = ov.available, rentedVehicles = ov.rented,
            reservedVehicles = ov.reserved, maintenanceVehicles = ov.maintenance,
        )
    }.distinctUntilChanged()

    // Local canonical metrics are authoritative & time-live; the API result is
    // the warm fallback before the first local computation (mirrors Desktop).
    val performanceMetricsFlow: Flow<PerformanceMetrics?> =
        combine(localMetricsFlow, _liveMetrics) { local, api -> local ?: api }

    private val _syncStatus = MutableStateFlow(SyncStatus())
    val syncStatusFlow: StateFlow<SyncStatus> = _syncStatus.asStateFlow()

    /**
     * TEMPORAL-CACHE COMPLETENESS INVARIANT (Increment 5).
     *
     * `true` once an authoritative full snapshot has been applied atomically
     * (`bootstrapAndReset` / `fullSync`) — Room then holds EVERY reservation
     * and maintenance interval the backend has, so the local canonical
     * derivation (`FleetStatus`) and the `BoundaryTicker` can evaluate every
     * future temporal boundary exactly like Desktop / Backend.
     *
     * `false` for a fresh install, or a cache written by a pre-Increment-5
     * build whose incremental refresh was page-capped and could silently drop
     * interval rows. While `false`, `refreshAll()` forces a full bootstrap
     * rather than presenting a possibly-sparse cache as a complete snapshot.
     */
    val cacheCompleteFlow: Flow<Boolean> =
        database.syncMetadataDao().observeValue(META_CACHE_COMPLETE)
            .map { it == "true" }
            .distinctUntilChanged()

    /** Revision watermark: "this device holds complete state through revision
     *  N" (backend `SyncBootstrapResponse.revision`). -1 ⇒ never fully synced. */
    suspend fun localRevision(): Long = withContext(Dispatchers.IO) {
        database.syncMetadataDao().getValue(META_SYNCED_THROUGH_REVISION)?.toLongOrNull() ?: -1L
    }

    private fun getCurrentTimeString(): String {
        val sdf = SimpleDateFormat("HH:mm", Locale.getDefault())
        return sdf.format(Date())
    }



    private fun mapVehicleDtoToDomain(dto: VehicleDto): Vehicle {
        // CANONICAL: render the backend-derived effective status so the Fleet
        // screen agrees with the Dashboard. Fall back to raw status only when
        // the server did not send one (older backend).
        val domainStatus = VehicleStatus.fromApi(dto.effectiveStatus ?: dto.status)

        val rootUrl = apiClient.getRootUrl()
        val imgUrl = ImageUrlResolver.resolve(dto.imageUrl, rootUrl, dto.version)
        val imagesList = dto.images?.mapNotNull { ImageUrlResolver.resolve(it.imageUrl, rootUrl, dto.version).takeIf { url -> url.isNotBlank() } } ?: emptyList()
        android.util.Log.d("IMAGE_DEBUG", "API URL = ${dto.imageUrl}")
        android.util.Log.d("IMAGE_DEBUG", "RESOLVED URL = $imgUrl")
        android.util.Log.d("IMAGE_DEBUG", "COIL image request = $imgUrl")

        val domainCategory = when {
            dto.brand.contains("Range", ignoreCase = true) || dto.model.contains("SUV", ignoreCase = true) -> "SUV"
            dto.model.contains("Coupé", ignoreCase = true) || dto.brand.contains("Porsche", ignoreCase = true) -> "Coupé"
            else -> "Berline"
        }
        return Vehicle(
            id = dto.id,
            brand = dto.brand,
            modelName = dto.model,
            plate = dto.registration,
            year = dto.year,
            category = domainCategory,
            dailyRate = dto.dailyRentalPrice.toInt(),
            status = domainStatus,
            mileage = dto.currentMileage,
            fuelType = dto.fuelType ?: "",
            transmission = dto.transmission ?: "",
            power = "",
            color = dto.color ?: "",
            imageUrl = imgUrl,
            images = imagesList,
            description = dto.notes ?: "",
            vin = dto.vin ?: "",
            deposit = (dto.dailyRentalPrice * 5).toInt(),
            version = dto.version
        )
    }

    private fun formatIsoDate(isoString: String?): String {
        if (isoString.isNullOrBlank()) return ""
        return try {
            val parser = java.text.SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss", java.util.Locale.getDefault())
            parser.timeZone = java.util.TimeZone.getTimeZone("UTC")
            val formatter = java.text.SimpleDateFormat("dd MMM yyyy, HH:mm", java.util.Locale.getDefault())
            formatter.timeZone = java.util.TimeZone.getDefault()
            val cleanIso = isoString.substringBefore(".").replace("Z", "")
            val date = parser.parse(cleanIso)
            date?.let { formatter.format(it) } ?: isoString.take(10)
        } catch (e: Exception) {
            isoString.take(10)
        }
    }

    private fun mapRentalDtoToDomain(dto: RentalDto): Reservation {
        val domainStatus = ReservationStatus.fromApi(dto.status)
        val vehicleName = listOfNotNull(dto.vehicleBrand, dto.vehicleModel)
            .joinToString(" ")
            .ifBlank { "Véhicule #${dto.vehicleId.take(4)}" }

        val startFormatted = formatIsoDate(dto.startDatetime)
        val endFormatted = formatIsoDate(dto.endDatetime)

        return Reservation(
            id = dto.id,
            clientName = dto.customerName ?: "Client Inconnu",
            clientPhone = dto.customerPhone ?: "",
            clientEmail = dto.customerEmail ?: "",
            identityCardImage = dto.identityCardImage ?: "",
            drivingLicenseImage = dto.drivingLicenseImage ?: "",
            vehicleId = dto.vehicleId,
            vehicleName = vehicleName,
            vehiclePlate = dto.vehicleRegistration ?: "",
            vehicleImageUrl = "",
            startDate = startFormatted,
            endDate = endFormatted,
            startIso = dto.startDatetime,
            endIso = dto.endDatetime,
            status = domainStatus,
            totalAmount = dto.totalPrice.toInt(),
            dailyPrice = dto.dailyPrice.toInt(),
            numDays = dto.numDays,
            deposit = dto.deposit.toInt(),
            paymentStatus = dto.paymentStatus,
            lastUpdated = "Synchronisé",
            pickupLocation = "",
            returnLocation = "",
            notes = dto.notes ?: ""
        )
    }

    private fun mapMaintenanceDtoToDomain(dto: MaintenanceDto): MaintenanceTicket {
        val vehicleName = listOfNotNull(dto.vehicleBrand, dto.vehicleModel)
            .joinToString(" ")
            .ifBlank { "Véhicule #${dto.vehicleId.take(4)}" }
        val vehiclePlate = dto.vehicleRegistration ?: ""

        return MaintenanceTicket(
            id = dto.id,
            vehicleId = dto.vehicleId,
            vehicleName = vehicleName,
            vehiclePlate = vehiclePlate,
            serviceItem = dto.type,
            title = dto.title,
            description = dto.description ?: "",
            diagnosis = dto.diagnosis,
            repair_description = dto.repairDescription,
            step = MaintenanceStep.fromApi(dto.step),
            status = dto.status,
            scheduledDate = formatIsoDate(dto.startDatetime),
            startIso = dto.startDatetime,
            expected_end_datetime = dto.expectedEndDatetime,
            actual_end_datetime = dto.actualEndDatetime,
            mileage = dto.mileage,
            location = dto.location,
            technician = dto.technicianName ?: "",
            invoice_number = dto.invoiceNumber,
            oil_brand = dto.oilBrand,
            oil_viscosity = dto.oilViscosity,
            oil_quantity = dto.oilQuantity,
            oil_filter_changed = dto.oilFilterChanged,
            air_filter_changed = dto.airFilterChanged,
            fuel_filter_changed = dto.fuelFilterChanged,
            cabin_filter_changed = dto.cabinFilterChanged,
            estimatedCost = dto.estimatedCost?.toInt() ?: 0,
            parts_cost = dto.partsCost,
            labor_cost = dto.laborCost,
            other_cost = dto.otherCost,
            actual_cost = dto.actualCost,
            next_maintenance_date = dto.nextMaintenanceDate,
            next_maintenance_mileage = dto.nextMaintenanceMileage,
            priority = "Haute",
            notes = dto.notes ?: "",
            parts = dto.parts.map { p ->
                com.example.data.model.MaintenancePart(
                    id = p.id,
                    part_name = p.partName,
                    quantity = p.quantity,
                    unit_price = p.unitPrice,
                    total_price = p.totalPrice,
                    notes = p.notes
                )
            }
        )
    }

    private fun mapNotificationDtoToDomain(dto: NotificationDto): NotificationItem {
        return NotificationItem(
            id = dto.id,
            vehicleId = dto.vehicleId,
            vehicleName = dto.vehicleName,
            vehiclePlate = dto.vehicleRegistration,
            type = dto.type,
            severity = dto.severity,
            title = dto.title,
            message = dto.message,
            dueDate = dto.dueDate,
            isRead = dto.isRead,
            createdAt = dto.createdAt
        )
    }

    /**
     * Checks lightweight health endpoint to test backend connectivity and compatibility.
     */
    suspend fun testConnection(): Result<String> = withContext(Dispatchers.IO) {
        try {
            Log.i("SYNC", "[SYNC] testConnection START -> ${apiClient.getBaseUrl()}sync/health")
            _syncStatus.value = _syncStatus.value.copy(
                state = SyncStatusState.CONNECTING,
                message = "Connexion au logiciel..."
            )
            val response = apiClient.getService().getHealth()
            Log.i("SYNC", "[SYNC] HEALTH RESPONSE CODE = ${response.code()}")
            if (response.isSuccessful && response.body() != null) {
                val body = response.body()!!
                Log.i("SYNC", "[SYNC] HEALTH SUCCESS: version=${body.version}, server_id=${body.serverId}")
                // Liveness passed; now check that the DATABASE is actually usable.
                when (probeServer()) {
                    ServerReachability.DATABASE_DOWN -> {
                        val err = "Serveur accessible, mais sa base de données est indisponible."
                        _syncStatus.value = _syncStatus.value.copy(
                            state = SyncStatusState.SERVER_DB_UNAVAILABLE,
                            message = err, errorMessage = err, serverId = body.serverId,
                            reachability = ServerReachability.DATABASE_DOWN
                        )
                        Result.failure(DbUnavailableException(err))
                    }
                    else -> {
                        _syncStatus.value = _syncStatus.value.copy(
                            state = SyncStatusState.CONNECTED,
                            message = "Connecté au serveur API (v${body.version})",
                            serverId = body.serverId,
                            reachability = ServerReachability.ONLINE
                        )
                        Result.success("Connecté (v${body.version})")
                    }
                }
            } else {
                val err = "Serveur inaccessible (Code: ${response.code()})"
                Log.e("SYNC", "[SYNC] HEALTH FAILED: $err")
                _syncStatus.value = _syncStatus.value.copy(
                    state = SyncStatusState.SYNC_ERROR,
                    message = err,
                    errorMessage = err,
                    reachability = ServerReachability.UNREACHABLE
                )
                Result.failure(Exception(err))
            }
        } catch (e: Exception) {
            Log.e("SYNC", "[SYNC] testConnection EXCEPTION: ${e.javaClass.name}: ${e.message}", e)
            val err = "Serveur inaccessible : ${e.localizedMessage ?: "Délai de connexion dépassé"}"
            _syncStatus.value = _syncStatus.value.copy(
                state = SyncStatusState.SYNC_ERROR,
                message = "Serveur inaccessible",
                errorMessage = err,
                reachability = ServerReachability.UNREACHABLE
            )
            Result.failure(e)
        }
    }

    /**
     * Classify backend availability via the readiness probe (`/health/ready`).
     *
     *   ONLINE        — reachable AND its database answered `SELECT 1`
     *   DATABASE_DOWN — reachable but readiness returned 503 / database:"unavailable"
     *   UNREACHABLE   — DNS / connect / timeout, or any non-503 transport failure
     *
     * Never throws. An older backend without `/health/ready` (404) falls back to
     * the liveness endpoint so it is still classified ONLINE vs UNREACHABLE.
     */
    suspend fun probeServer(): ServerReachability = withContext(Dispatchers.IO) {
        try {
            val ready = apiClient.getService().getReadiness()
            val body = ready.body()
            when {
                ready.isSuccessful && (body?.status == "ready" || body?.database == "connected") ->
                    ServerReachability.ONLINE
                ready.code() == 503 || body?.database == "unavailable" || body?.status == "not_ready" ->
                    ServerReachability.DATABASE_DOWN
                ready.code() == 404 -> {
                    val live = try { apiClient.getService().getHealth() } catch (e: Exception) { null }
                    if (live?.isSuccessful == true) ServerReachability.ONLINE
                    else ServerReachability.UNREACHABLE
                }
                else -> ServerReachability.UNREACHABLE
            }
        } catch (e: Exception) {
            Log.w("SYNC", "[SYNC] probeServer transport failure: ${e.message}")
            ServerReachability.UNREACHABLE
        }
    }

    /**
     * Publish a failed-sync status WITHOUT touching Room. When the server's
     * database is down we surface a distinct, non-alarming state and keep the
     * cached snapshot on screen; a genuine transport failure stays SYNC_ERROR.
     */
    private suspend fun publishSyncFailure(cause: Throwable?) {
        val reach = when (cause) {
            is DbUnavailableException -> ServerReachability.DATABASE_DOWN
            else -> probeServer()
        }
        val dbDown = reach == ServerReachability.DATABASE_DOWN
        _syncStatus.value = _syncStatus.value.copy(
            state = if (dbDown) SyncStatusState.SERVER_DB_UNAVAILABLE else SyncStatusState.SYNC_ERROR,
            message = if (dbDown)
                "Base de données du serveur indisponible — données hors ligne affichées"
            else "Synchronisation échouée — données hors ligne affichées",
            errorMessage = cause?.localizedMessage ?: "Erreur de synchronisation",
            reachability = reach
        )
    }

    /**
     * Clear all local mobile business data cleanly.
     */
    suspend fun resetLocalBusinessData(): Unit = withContext(Dispatchers.IO) {
        database.withTransaction {
            database.vehicleDao().clearAll()
            database.reservationDao().clearAll()
            database.maintenanceDao().clearAll()
            database.notificationDao().clearAll()
            database.syncMetadataDao().clearAll()
        }
        _notifications.value = emptyList()
        _liveMetrics.value = null
    }

    private fun collectVehicleImageEntities(vehicles: List<VehicleDto>): List<VehicleImageEntity> {
        val out = mutableListOf<VehicleImageEntity>()
        vehicles.forEach { v ->
            v.images?.forEach { img ->
                out.add(VehicleImageEntity(
                    id = img.id ?: java.util.UUID.randomUUID().toString(),
                    vehicleId = v.id,
                    imageUrl = img.imageUrl ?: "",
                    sortOrder = img.sortOrder ?: 0,
                ))
            }
            if (v.images == null && !v.imageUrl.isNullOrBlank()) {
                v.imageUrl.split(",").map { it.trim() }.filter { it.isNotBlank() }
                    .forEachIndexed { index, url ->
                        out.add(VehicleImageEntity(vehicleId = v.id, imageUrl = url, sortOrder = index))
                    }
            }
        }
        return out
    }

    /**
     * Atomically replace the ENTIRE local temporal projection with an
     * authoritative backend snapshot, in ONE Room transaction — an observer
     * moves from the old complete snapshot straight to the new one and can
     * never see `vehicles = new, reservations = old/empty` in between.
     *
     * Revision safety (reuses the backend `SyncBootstrapResponse.revision`):
     *   - a snapshot OLDER than the revision we already hold is rejected (stale)
     *   - an equal revision is applied idempotently (same rows back in)
     *   - the completeness flag + revision watermark are written INSIDE the
     *     same transaction, so "cache complete through revision N" is atomic
     *     with the data it describes.
     *
     * @return true when applied, false when rejected as stale.
     */
    internal suspend fun applyAuthoritativeSnapshot(data: SyncBootstrapResponseDto): Boolean =
        withContext(Dispatchers.IO) {
            val localRev = database.syncMetadataDao()
                .getValue(META_SYNCED_THROUGH_REVISION)?.toLongOrNull() ?: -1L
            if (data.revision in 1 until localRev) {
                Log.w("SYNC", "[SYNC] Rejecting STALE snapshot revision=${data.revision} < local=$localRev")
                return@withContext false
            }

            val vehiclesDomain = data.vehicles.map { mapVehicleDtoToDomain(it) }
            val rentalsDomain = data.rentals.map { mapRentalDtoToDomain(it) }
            val maintenanceDomain = data.maintenance.map { mapMaintenanceDtoToDomain(it) }
            val notifsDomain = data.notifications.map { mapNotificationDtoToDomain(it) }

            val vehicleEntities = vehiclesDomain.map { VehicleEntity.fromDomain(it) }
            val rentalEntities = rentalsDomain.map { ReservationEntity.fromDomain(it) }
            val maintenanceEntities = maintenanceDomain.map { MaintenanceEntity.fromDomain(it) }
            val notifEntities = notifsDomain.map { NotificationEntity.fromDomain(it) }
            val allImages = collectVehicleImageEntities(data.vehicles)
            val syncTime = getCurrentTimeString()
            val effectiveRevision = maxOf(data.revision, if (localRev < 0L) 0L else localRev)

            database.withTransaction {
                database.vehicleDao().clearAll()
                database.reservationDao().clearAll()
                database.maintenanceDao().clearAll()
                database.notificationDao().clearAll()

                database.vehicleDao().insertVehicles(vehicleEntities)
                if (allImages.isNotEmpty()) database.vehicleDao().insertVehicleImages(allImages)
                database.reservationDao().insertReservations(rentalEntities)
                database.maintenanceDao().insertTickets(maintenanceEntities)
                database.notificationDao().insertNotifications(notifEntities)

                database.syncMetadataDao().setValue(SyncMetadataEntity(META_IS_BOOTSTRAPPED, "true"))
                database.syncMetadataDao().setValue(SyncMetadataEntity(META_CACHE_COMPLETE, "true"))
                database.syncMetadataDao().setValue(
                    SyncMetadataEntity(META_SYNCED_THROUGH_REVISION, effectiveRevision.toString())
                )
                database.syncMetadataDao().setValue(SyncMetadataEntity("last_sync_at", syncTime))
                database.syncMetadataDao().setValue(SyncMetadataEntity("server_id", data.serverId))
                database.syncMetadataDao().setValue(SyncMetadataEntity("sync_version", data.syncVersion.toString()))
            }
            _notifications.value = notifsDomain
            Log.i("SYNC", "[SYNC] snapshot applied — complete through revision $effectiveRevision " +
                "(${vehicleEntities.size} vehicles, ${rentalEntities.size} reservations, " +
                "${maintenanceEntities.size} maintenance)")
            true
        }

    /**
     * Versioned full-sync — the mobile "incremental" path. It pulls the
     * authoritative snapshot from `/sync/bootstrap` and applies it atomically,
     * so unlike a page-capped per-list refresh it is STRUCTURALLY incapable of
     * leaving a sparse temporal cache. Revision-guarded against stale apply.
     * On any failure the previous complete snapshot is left intact.
     */
    suspend fun fullSync(): Result<Unit> = withContext(Dispatchers.IO) {
        try {
            val res = apiClient.getService().getBootstrap()
            if (!res.isSuccessful || res.body() == null) {
                // 503 == server up, database temporarily unavailable. Keep the
                // existing complete snapshot; this is not a transport failure.
                if (res.code() == 503) {
                    return@withContext Result.failure(
                        DbUnavailableException("Base de données du serveur indisponible (HTTP 503).")
                    )
                }
                return@withContext Result.failure(
                    Exception("Snapshot serveur indisponible : HTTP ${res.code()}")
                )
            }
            applyAuthoritativeSnapshot(res.body()!!)
            refreshDashboard()
            Result.success(Unit)
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    /**
     * Complete CONNECT -> RESET -> INITIAL BOOTSTRAP workflow.
     * Atomically purges stale cache and populates Room DB with authoritative server snapshot.
     */
    suspend fun bootstrapAndReset(): Result<Unit> = withContext(Dispatchers.IO) {
        try {
            Log.i("SYNC", "[SYNC] START")
            Log.i("SYNC", "[SYNC] API URL = ${apiClient.getBaseUrl()}")
            Log.i("SYNC", "[SYNC] CONNECTING")

            _syncStatus.value = _syncStatus.value.copy(
                state = SyncStatusState.CONNECTING,
                message = "Connexion au logiciel..."
            )

            // Step 1: readiness probe — distinguish unreachable vs DB-down vs OK
            when (probeServer()) {
                ServerReachability.DATABASE_DOWN ->
                    throw DbUnavailableException("Serveur accessible, mais sa base de données est indisponible.")
                ServerReachability.UNREACHABLE ->
                    throw Exception("Serveur inaccessible.")
                else -> { /* ONLINE (or liveness-only older backend) → proceed */ }
            }

            _syncStatus.value = _syncStatus.value.copy(
                state = SyncStatusState.RESETTING,
                message = "Réinitialisation des données locales..."
            )

            // Step 2: Fetch authoritative server snapshot
            _syncStatus.value = _syncStatus.value.copy(
                state = SyncStatusState.SYNCING,
                message = "Synchronisation des données..."
            )

            Log.i("SYNC", "[SYNC] Fetching bootstrap snapshot from ${apiClient.getBaseUrl()}sync/bootstrap")
            val bootstrapRes = apiClient.getService().getBootstrap()
            Log.i("SYNC", "[SYNC] BOOTSTRAP RESPONSE CODE = ${bootstrapRes.code()}")
            if (!bootstrapRes.isSuccessful || bootstrapRes.body() == null) {
                val errorBody = bootstrapRes.errorBody()?.string() ?: ""
                Log.e("SYNC", "[SYNC] BOOTSTRAP FAILED HTTP ${bootstrapRes.code()}: $errorBody")
                if (bootstrapRes.code() == 503) {
                    throw DbUnavailableException("Base de données du serveur indisponible (HTTP 503).")
                }
                throw Exception("Échec du téléchargement du snapshot serveur : HTTP ${bootstrapRes.code()}")
            }

            val data = bootstrapRes.body()!!
            Log.i("SYNC", "[SYNC] API SUCCESS")
            Log.i("SYNC", "[SYNC] VEHICLES RECEIVED = ${data.vehicles.size}")
            Log.i("SYNC", "[SYNC] RESERVATIONS RECEIVED = ${data.rentals.size}")
            Log.i("SYNC", "[SYNC] MAINTENANCE RECEIVED = ${data.maintenance.size}")
            Log.i("SYNC", "[SYNC] NOTIFICATIONS RECEIVED = ${data.notifications.size}")
            Log.i("SYNC", "[SYNC] SNAPSHOT REVISION = ${data.revision}")

            val syncTime = getCurrentTimeString()

            // Step 3: Atomic authoritative apply — one Room transaction,
            // complete temporal projection, completeness flag + revision
            // watermark written inside the same transaction.
            Log.i("SYNC", "[SYNC] WRITING ROOM")
            applyAuthoritativeSnapshot(data)
            Log.i("SYNC", "[SYNC] ROOM COMMIT SUCCESS")

            // Also refresh live dashboard stats
            refreshDashboard()

            _syncStatus.value = SyncStatus(
                state = SyncStatusState.SYNCED,
                message = "Synchronisation terminée",
                lastSyncTime = syncTime,
                serverId = data.serverId,
                isBootstrapped = true,
                errorMessage = null
            )
            Log.i("SYNC", "[SYNC] BOOTSTRAP AND RESET COMPLETED SUCCESSFULLY")

            Result.success(Unit)
        } catch (e: Exception) {
            val errMsg = e.localizedMessage ?: "Synchronisation échouée"
            Log.e("SYNC", "SYNC FAILED\ntype=NETWORK\nendpoint=/api/v1/sync/bootstrap\nstatus=0\nmessage=$errMsg", e)
            // Publish the failure WITHOUT touching Room — the previous complete
            // snapshot (if any) stays on screen; the UI shows an offline banner,
            // not a fatal error, whenever cached rows exist.
            publishSyncFailure(e)
            Result.failure(e)
        }
    }

    // ── page-complete fetchers ───────────────────────────────────────────
    // The backend list endpoints are paginated (vehicles ≤ 500/page,
    // rentals ≤ 100/page, maintenance ≤ 100/page). Fetching only page 1
    // silently truncated the cache for any fleet larger than one page — the
    // sparse-cache root cause. These loop every page so a per-entity refresh
    // is also a COMPLETE rebuild.
    private val MAX_PAGES = 500

    private suspend fun fetchAllVehicleDtos(): List<VehicleDto> {
        val out = ArrayList<VehicleDto>()
        var page = 1
        while (page <= MAX_PAGES) {
            val resp = apiClient.getService().getVehicles(page = page, pageSize = 500)
            // Any page failure aborts the whole fetch — a partial list must
            // NEVER be written (that is the sparse-cache failure mode).
            if (!resp.isSuccessful || resp.body() == null) {
                throw Exception("Erreur serveur véhicules (page $page): ${resp.code()}")
            }
            val body = resp.body()!!
            out.addAll(body.vehicles)
            if (body.vehicles.isEmpty() || body.vehicles.size < 500 || out.size >= body.total) break
            page++
        }
        return out
    }

    private suspend fun fetchAllRentalDtos(): List<RentalDto> {
        val out = ArrayList<RentalDto>()
        var page = 1
        while (page <= MAX_PAGES) {
            val resp = apiClient.getService().getRentals(page = page, pageSize = 100)
            if (!resp.isSuccessful || resp.body() == null) {
                throw Exception("Erreur serveur réservations (page $page): ${resp.code()}")
            }
            val body = resp.body()!!
            out.addAll(body.rentals)
            if (body.rentals.isEmpty() || body.rentals.size < 100 || out.size >= body.total) break
            page++
        }
        return out
    }

    private suspend fun fetchAllMaintenanceDtos(): List<MaintenanceDto> {
        val out = ArrayList<MaintenanceDto>()
        var page = 1
        while (page <= MAX_PAGES) {
            val resp = apiClient.getService().getMaintenances(page = page, size = 100)
            if (!resp.isSuccessful || resp.body() == null) {
                throw Exception("Erreur serveur maintenance (page $page): ${resp.code()}")
            }
            val body = resp.body()!!
            out.addAll(body.items)
            if (body.items.isEmpty() || body.items.size < 100 || out.size >= body.total) break
            page++
        }
        return out
    }

    suspend fun refreshVehicles(): Result<List<Vehicle>> = withContext(Dispatchers.IO) {
        try {
            val dtos = fetchAllVehicleDtos()
            val list = dtos.map { mapVehicleDtoToDomain(it) }
            val entities = list.map { VehicleEntity.fromDomain(it) }
            val allImages = collectVehicleImageEntities(dtos)
            database.withTransaction {
                database.vehicleDao().clearAll()
                database.vehicleDao().insertVehicles(entities)
                dtos.forEach { database.vehicleDao().deleteImagesForVehicle(it.id) }
                if (allImages.isNotEmpty()) {
                    database.vehicleDao().insertVehicleImages(allImages)
                }
            }
            Result.success(list)
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    suspend fun refreshRentals(): Result<List<Reservation>> = withContext(Dispatchers.IO) {
        try {
            val list = fetchAllRentalDtos().map { mapRentalDtoToDomain(it) }
            val entities = list.map { ReservationEntity.fromDomain(it) }
            database.withTransaction {
                database.reservationDao().clearAll()
                database.reservationDao().insertReservations(entities)
            }
            Result.success(list)
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    suspend fun refreshMaintenances(): Result<List<MaintenanceTicket>> = withContext(Dispatchers.IO) {
        try {
            val list = fetchAllMaintenanceDtos().map { mapMaintenanceDtoToDomain(it) }
            val entities = list.map { MaintenanceEntity.fromDomain(it) }
            database.withTransaction {
                database.maintenanceDao().clearAll()
                database.maintenanceDao().insertTickets(entities)
            }
            Result.success(list)
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    suspend fun refreshDashboard(): Result<Unit> = withContext(Dispatchers.IO) {
        try {
            val response = apiClient.getService().getDashboardStats()
            if (response.isSuccessful && response.body() != null) {
                val stats = response.body()!!
                _liveMetrics.value = PerformanceMetrics(
                    todayBookings = stats.todayRentals,
                    weekBookings = stats.weekRentals,
                    monthBookings = stats.monthRentals,
                    todayRevenue = stats.todayRevenue,
                    weekRevenue = stats.weekRevenue,
                    monthRevenue = stats.monthRevenue,
                    readyVehicles = stats.available,
                    rentedVehicles = stats.rented,
                    reservedVehicles = stats.reserved,
                    maintenanceVehicles = stats.maintenance
                )
                Result.success(Unit)
            } else {
                Result.failure(Exception("Erreur serveur stats: ${response.code()}"))
            }
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    suspend fun refreshNotifications(): Result<List<NotificationItem>> = withContext(Dispatchers.IO) {
        try {
            val response = apiClient.getService().getNotifications(page = 1, pageSize = 50)
            if (response.isSuccessful && response.body() != null) {
                val list = response.body()!!.items.map { mapNotificationDtoToDomain(it) }
                val entities = list.map { NotificationEntity.fromDomain(it) }
                database.withTransaction {
                    database.notificationDao().clearAll()
                    database.notificationDao().insertNotifications(entities)
                }
                _notifications.value = list
                Result.success(list)
            } else {
                Result.failure(Exception("Erreur serveur notifications: ${response.code()}"))
            }
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    suspend fun markNotificationRead(id: String): Result<Unit> = withContext(Dispatchers.IO) {
        try {
            val response = apiClient.getService().markNotificationRead(id)
            if (response.isSuccessful) {
                database.notificationDao().markAsRead(id)
                _notifications.value = _notifications.value.map {
                    if (it.id == id) it.copy(isRead = true) else it
                }
                Result.success(Unit)
            } else {
                Result.failure(Exception("Erreur serveur: ${response.code()}"))
            }
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    suspend fun markAllNotificationsRead(): Result<Unit> = withContext(Dispatchers.IO) {
        try {
            val response = apiClient.getService().markAllNotificationsRead()
            if (response.isSuccessful) {
                database.notificationDao().markAllAsRead()
                _notifications.value = _notifications.value.map { it.copy(isRead = true) }
                Result.success(Unit)
            } else {
                Result.failure(Exception("Erreur serveur: ${response.code()}"))
            }
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    /**
     * Refreshes all entities.
     *
     * Increment 5: a partial cache is NEVER continued as if complete.
     *  - never bootstrapped, OR the completeness flag is not set (fresh install
     *    / cache from a pre-Increment-5 page-capped build) ⇒ full bootstrap.
     *  - otherwise ⇒ versioned full-sync (`fullSync`): a complete atomic
     *    rebuild from `/sync/bootstrap`, revision-guarded, that cannot leave a
     *    sparse temporal cache. On failure the previous complete snapshot is
     *    left untouched (atomic apply).
     */
    suspend fun refreshAll(): Result<Unit> = withContext(Dispatchers.IO) {
        val isBootstrapped = database.syncMetadataDao().getValue(META_IS_BOOTSTRAPPED) == "true"
        val cacheComplete = database.syncMetadataDao().getValue(META_CACHE_COMPLETE) == "true"
        Log.i("SYNC", "[SYNC] refreshAll START (isBootstrapped=$isBootstrapped, cacheComplete=$cacheComplete)")

        if (!isBootstrapped || !cacheComplete) {
            Log.i("SYNC", "[SYNC] cache not proven complete → forcing full bootstrap recovery")
            return@withContext bootstrapAndReset()
        }

        _syncStatus.value = _syncStatus.value.copy(
            state = SyncStatusState.SYNCING,
            message = "Synchronisation des données..."
        )

        val result = fullSync()
        if (result.isSuccess) {
            val syncTime = getCurrentTimeString()
            _syncStatus.value = SyncStatus(
                state = SyncStatusState.SYNCED,
                message = "Synchronisation terminée",
                lastSyncTime = syncTime,
                isBootstrapped = true,
                errorMessage = null,
                reachability = ServerReachability.ONLINE
            )
            Log.i("SYNC", "[SYNC] refreshAll SUCCESS (versioned full-sync, rev=${localRevision()})")
            Result.success(Unit)
        } else {
            val cause = result.exceptionOrNull()
            val errMsg = cause?.message ?: "Erreur de synchronisation"
            Log.e("SYNC", "SYNC FAILED\ntype=NETWORK\nendpoint=/api/v1/sync/bootstrap\nstatus=0\nmessage=$errMsg")
            // The prior complete snapshot is untouched (fullSync applies
            // atomically only on success). Publish a non-fatal offline status
            // and let the screens fall back to the cached rows.
            publishSyncFailure(cause)
            Result.failure(Exception(errMsg))
        }
    }

    /**
     * Updates real-time WebSocket connection state flag in SyncStatus.
     */
    fun updateRealtimeConnection(isConnected: Boolean) {
        val currentState = _syncStatus.value
        _syncStatus.value = currentState.copy(
            isRealtimeConnected = isConnected,
            state = if (isConnected) SyncStatusState.REALTIME_ACTIVE else if (currentState.isBootstrapped) SyncStatusState.SYNCED else SyncStatusState.DISCONNECTED,
            message = if (isConnected) "En direct (Temps réel)" else if (currentState.isBootstrapped) "Synchronisation terminée" else "Déconnecté"
        )
    }

    /**
     * Handles an incoming real-time WebSocket event from the backend.
     * Requests the authoritative latest data from FastAPI and updates Room database atomically.
     */
    suspend fun handleRealtimeEvent(event: WebSocketEventDto): Result<Unit> = withContext(Dispatchers.IO) {
        try {
            val eventType = (event.eventType ?: event.type ?: "").uppercase()
            val entityType = (event.entityType ?: event.entity ?: "").lowercase()
            val entityId = event.entityId ?: event.vehicleId

            val syncTime = getCurrentTimeString()
            Log.i("SYNC", "[SYNC] handleRealtimeEvent: type=$eventType, entity=$entityType, id=$entityId")

            when {
                // ──── VEHICLE EVENTS ────
                entityType == "vehicle" || eventType.startsWith("VEHICLE_") -> {
                    if (eventType.contains("DELETE")) {
                        if (!entityId.isNullOrBlank()) {
                            Log.i("SYNC", "[SYNC] Room: Deleting vehicle $entityId")
                            database.vehicleDao().deleteVehicle(entityId)
                        } else {
                            refreshVehicles()
                        }
                    } else {
                        if (!entityId.isNullOrBlank()) {
                            try {
                                val res = apiClient.getService().getVehicle(entityId)
                                if (res.isSuccessful && res.body() != null) {
                                    val domain = mapVehicleDtoToDomain(res.body()!!)
                                    database.vehicleDao().insertVehicle(VehicleEntity.fromDomain(domain))
                                    Log.i("SYNC", "[SYNC] Room: Upserted vehicle ${domain.brand} ${domain.modelName} (${domain.plate})")
                                } else {
                                    refreshVehicles()
                                }
                            } catch (e: Exception) {
                                Log.w("SYNC", "[SYNC] Failed to fetch single vehicle $entityId, refreshing all: ${e.message}")
                                refreshVehicles()
                            }
                        } else {
                            refreshVehicles()
                        }
                    }
                }

                // ──── RESERVATION EVENTS ────
                entityType == "reservation" || entityType == "rental" || eventType.startsWith("RESERVATION_") || eventType.startsWith("RENTAL_") -> {
                    if (eventType.contains("DELETE")) {
                        if (!entityId.isNullOrBlank()) {
                            Log.i("SYNC", "[SYNC] Room: Deleting reservation $entityId")
                            database.reservationDao().deleteReservation(entityId)
                        } else {
                            refreshRentals()
                        }
                    } else {
                        if (!entityId.isNullOrBlank()) {
                            try {
                                val res = apiClient.getService().getRental(entityId)
                                if (res.isSuccessful && res.body() != null) {
                                    val domain = mapRentalDtoToDomain(res.body()!!)
                                    database.reservationDao().insertReservation(ReservationEntity.fromDomain(domain))
                                    Log.i("SYNC", "[SYNC] Room: Upserted reservation ${domain.id}")
                                } else {
                                    refreshRentals()
                                }
                            } catch (e: Exception) {
                                Log.w("SYNC", "[SYNC] Failed to fetch single rental $entityId, refreshing all: ${e.message}")
                                refreshRentals()
                            }
                        } else {
                            refreshRentals()
                        }
                    }
                    // Also refresh vehicle status if vehicleId is provided
                    val vehId = event.vehicleId
                    if (!vehId.isNullOrBlank()) {
                        try {
                            val vRes = apiClient.getService().getVehicle(vehId)
                            if (vRes.isSuccessful && vRes.body() != null) {
                                database.vehicleDao().insertVehicle(VehicleEntity.fromDomain(mapVehicleDtoToDomain(vRes.body()!!)))
                            }
                        } catch (_: Exception) {}
                    }
                    refreshNotifications()
                }

                // ──── MAINTENANCE EVENTS ────
                entityType == "maintenance" || eventType.startsWith("MAINTENANCE_") -> {
                    if (eventType.contains("DELETE") || eventType.contains("CLOSE")) {
                        if (!entityId.isNullOrBlank()) {
                            Log.i("SYNC", "[SYNC] Room: Deleting maintenance ticket $entityId")
                            database.maintenanceDao().deleteTicket(entityId)
                        } else {
                            refreshMaintenances()
                        }
                    } else {
                        if (!entityId.isNullOrBlank()) {
                            try {
                                val res = apiClient.getService().getMaintenance(entityId)
                                if (res.isSuccessful && res.body() != null) {
                                    val domain = mapMaintenanceDtoToDomain(res.body()!!)
                                    database.maintenanceDao().insertTicket(MaintenanceEntity.fromDomain(domain))
                                    Log.i("SYNC", "[SYNC] Room: Upserted maintenance ticket ${domain.id} (${domain.serviceItem})")
                                } else {
                                    refreshMaintenances()
                                }
                            } catch (e: Exception) {
                                Log.w("SYNC", "[SYNC] Failed to fetch single maintenance $entityId, refreshing all: ${e.message}")
                                refreshMaintenances()
                            }
                        } else {
                            refreshMaintenances()
                        }
                    }
                    // Also refresh vehicle status if vehicleId is provided
                    val vehId = event.vehicleId
                    if (!vehId.isNullOrBlank()) {
                        try {
                            val vRes = apiClient.getService().getVehicle(vehId)
                            if (vRes.isSuccessful && vRes.body() != null) {
                                database.vehicleDao().insertVehicle(VehicleEntity.fromDomain(mapVehicleDtoToDomain(vRes.body()!!)))
                            }
                        } catch (_: Exception) {}
                    }
                    refreshNotifications()
                }

                // ──── NOTIFICATION EVENTS ────
                entityType == "notification" || eventType.startsWith("NOTIFICATION") -> {
                    if (eventType == "NOTIFICATION_CREATED") {
                        val title = "Notification Système"
                        val message = event.message ?: "Vous avez reçu une notification."
                        val notifId = event.entityId?.hashCode() ?: (title + message).hashCode()
                        com.example.util.NotificationHelper.showNotification(context, title, message, notifId)
                    }
                    refreshNotifications()
                }

                // ──── DEFAULT FALLBACK ────
                else -> {
                    refreshAll()
                }
            }

            // Always keep live operational KPI dashboard stats in sync
            refreshDashboard()

            // Update sync metadata and live status
            database.syncMetadataDao().setValue(SyncMetadataEntity("last_sync_at", syncTime))
            _syncStatus.value = _syncStatus.value.copy(
                lastSyncTime = syncTime,
                message = "En direct (Temps réel)",
                errorMessage = null
            )

            Result.success(Unit)
        } catch (e: Exception) {
            Log.e("SYNC", "[SYNC] handleRealtimeEvent error: ${e.message}", e)
            Result.failure(e)
        }
    }

    // ── Clients (read-only, canonical backend contract) ──

    suspend fun getClients(search: String? = null): Result<List<ClientDto>> =
        withContext(Dispatchers.IO) {
            try {
                val response = apiClient.getService().getClients(search = search)
                if (response.isSuccessful && response.body() != null) {
                    Result.success(response.body()!!.clients)
                } else {
                    Result.failure(Exception("HTTP ${'$'}{response.code()}"))
                }
            } catch (e: Exception) {
                Log.e("CLIENTS", "getClients failed: ${'$'}{e.message}")
                Result.failure(e)
            }
        }

    suspend fun getClientRentalsReport(clientId: String): Result<ClientRentalsReportDto> =
        withContext(Dispatchers.IO) {
            try {
                val response = apiClient.getService().getClientRentalsReport(clientId)
                if (response.isSuccessful && response.body() != null) {
                    Result.success(response.body()!!)
                } else {
                    Result.failure(Exception("HTTP ${'$'}{response.code()}"))
                }
            } catch (e: Exception) {
                Log.e("CLIENTS", "client report failed: ${'$'}{e.message}")
                Result.failure(e)
            }
        }
}
