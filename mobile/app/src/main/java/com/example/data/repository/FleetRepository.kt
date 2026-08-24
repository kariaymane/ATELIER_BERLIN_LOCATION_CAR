package com.example.data.repository

import android.util.Log
import androidx.room.withTransaction
import com.example.data.api.ApiClient
import com.example.data.api.ClientRentalsReportDto
import com.example.data.api.ClientDto
import com.example.data.api.MaintenanceDto
import com.example.data.api.NotificationDto
import com.example.data.api.RentalDto
import com.example.data.api.VehicleDto
import com.example.data.api.WebSocketEventDto
import com.example.data.local.*
import com.example.data.model.*
import com.example.util.ImageUrlResolver
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.withContext
import java.text.SimpleDateFormat
import java.util.*

class FleetRepository(
    private val apiClient: ApiClient,
    private val database: AppDatabase,
    private val context: android.content.Context
) {
    val vehiclesFlow: Flow<List<Vehicle>> = database.vehicleDao().getAllVehicles().map { list ->
        list.map { it.toDomain() }
    }

    val reservationsFlow: Flow<List<Reservation>> = database.reservationDao().getAllReservations().map { list ->
        list.map { it.toDomain() }
    }

    val maintenanceFlow: Flow<List<MaintenanceTicket>> = database.maintenanceDao().getAllTickets().map { list ->
        list.map { it.toDomain() }
    }

    private val _notifications = MutableStateFlow<List<NotificationItem>>(emptyList())
    val notificationsFlow: StateFlow<List<NotificationItem>> = _notifications.asStateFlow()

    private val _liveMetrics = MutableStateFlow<PerformanceMetrics?>(null)
    val performanceMetricsFlow: Flow<PerformanceMetrics?> = _liveMetrics.asStateFlow()

    private val _syncStatus = MutableStateFlow(SyncStatus())
    val syncStatusFlow: StateFlow<SyncStatus> = _syncStatus.asStateFlow()

    private fun getCurrentTimeString(): String {
        val sdf = SimpleDateFormat("HH:mm", Locale.getDefault())
        return sdf.format(Date())
    }



    private fun mapVehicleDtoToDomain(dto: VehicleDto): Vehicle {
        val domainStatus = VehicleStatus.fromApi(dto.status)

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
                _syncStatus.value = _syncStatus.value.copy(
                    state = SyncStatusState.CONNECTED,
                    message = "Connecté au serveur API (v${body.version})",
                    serverId = body.serverId
                )
                Result.success("Connecté (v${body.version})")
            } else {
                val err = "Serveur inaccessible (Code: ${response.code()})"
                Log.e("SYNC", "[SYNC] HEALTH FAILED: $err")
                _syncStatus.value = _syncStatus.value.copy(
                    state = SyncStatusState.SYNC_ERROR,
                    message = err,
                    errorMessage = err
                )
                Result.failure(Exception(err))
            }
        } catch (e: Exception) {
            Log.e("SYNC", "[SYNC] testConnection EXCEPTION: ${e.javaClass.name}: ${e.message}", e)
            val err = "Serveur inaccessible : ${e.localizedMessage ?: "Délai de connexion dépassé"}"
            _syncStatus.value = _syncStatus.value.copy(
                state = SyncStatusState.SYNC_ERROR,
                message = "Serveur inaccessible",
                errorMessage = err
            )
            Result.failure(e)
        }
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

            // Step 1: Health check
            val healthRes = apiClient.getService().getHealth()
            Log.i("SYNC", "[SYNC] HEALTH RESPONSE CODE = ${healthRes.code()}")
            if (!healthRes.isSuccessful) {
                throw Exception("Serveur inaccessible : HTTP ${healthRes.code()}")
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
                throw Exception("Échec du téléchargement du snapshot serveur : HTTP ${bootstrapRes.code()}")
            }

            val data = bootstrapRes.body()!!
            Log.i("SYNC", "[SYNC] API SUCCESS")
            Log.i("SYNC", "[SYNC] VEHICLES RECEIVED = ${data.vehicles.size}")
            Log.i("SYNC", "[SYNC] RESERVATIONS RECEIVED = ${data.rentals.size}")
            Log.i("SYNC", "[SYNC] MAINTENANCE RECEIVED = ${data.maintenance.size}")
            Log.i("SYNC", "[SYNC] NOTIFICATIONS RECEIVED = ${data.notifications.size}")

            val vehiclesDomain = data.vehicles.map { mapVehicleDtoToDomain(it) }
            val rentalsDomain = data.rentals.map { mapRentalDtoToDomain(it) }
            val maintenanceDomain = data.maintenance.map { mapMaintenanceDtoToDomain(it) }
            val notifsDomain = data.notifications.map { mapNotificationDtoToDomain(it) }

            val vehicleEntities = vehiclesDomain.map { VehicleEntity.fromDomain(it) }
            val rentalEntities = rentalsDomain.map { ReservationEntity.fromDomain(it) }
            val maintenanceEntities = maintenanceDomain.map { MaintenanceEntity.fromDomain(it) }
            val notifEntities = notifsDomain.map { NotificationEntity.fromDomain(it) }

            val syncTime = getCurrentTimeString()

            // Step 3: Atomic Room Transaction
            Log.i("SYNC", "[SYNC] WRITING ROOM")
            database.withTransaction {
                database.vehicleDao().clearAll()
                database.reservationDao().clearAll()
                database.maintenanceDao().clearAll()
                database.notificationDao().clearAll()

                database.vehicleDao().insertVehicles(vehicleEntities)
                val allImages = mutableListOf<VehicleImageEntity>()
                data.vehicles.forEach { v ->
                    v.images?.forEach { img ->
                        allImages.add(VehicleImageEntity(
                            id = img.id ?: java.util.UUID.randomUUID().toString(),
                            vehicleId = v.id,
                            imageUrl = img.imageUrl ?: "",
                            sortOrder = img.sortOrder ?: 0
                        ))
                    }
                    if (v.images == null && !v.imageUrl.isNullOrBlank()) {
                        v.imageUrl.split(",").map { it.trim() }.filter { it.isNotBlank() }.forEachIndexed { index, url ->
                            allImages.add(VehicleImageEntity(
                                vehicleId = v.id,
                                imageUrl = url,
                                sortOrder = index
                            ))
                        }
                    }
                }
                if (allImages.isNotEmpty()) {
                    database.vehicleDao().insertVehicleImages(allImages)
                }
                database.reservationDao().insertReservations(rentalEntities)
                database.maintenanceDao().insertTickets(maintenanceEntities)
                database.notificationDao().insertNotifications(notifEntities)

                database.syncMetadataDao().setValue(SyncMetadataEntity("is_bootstrapped", "true"))
                database.syncMetadataDao().setValue(SyncMetadataEntity("last_sync_at", syncTime))
                database.syncMetadataDao().setValue(SyncMetadataEntity("server_id", data.serverId))
                database.syncMetadataDao().setValue(SyncMetadataEntity("sync_version", data.syncVersion.toString()))
            }
            Log.i("SYNC", "[SYNC] ROOM COMMIT SUCCESS")

            _notifications.value = notifsDomain

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
            _syncStatus.value = _syncStatus.value.copy(
                state = SyncStatusState.SYNC_ERROR,
                message = "Synchronisation échouée",
                errorMessage = errMsg
            )
            Result.failure(e)
        }
    }

    suspend fun refreshVehicles(): Result<List<Vehicle>> = withContext(Dispatchers.IO) {
        try {
            val response = apiClient.getService().getVehicles(page = 1, pageSize = 100)
            if (response.isSuccessful && response.body() != null) {
                val list = response.body()!!.vehicles.map { mapVehicleDtoToDomain(it) }
                val entities = list.map { VehicleEntity.fromDomain(it) }
                database.withTransaction {
                    database.vehicleDao().clearAll()
                    database.vehicleDao().insertVehicles(entities)
                    val allImages = mutableListOf<VehicleImageEntity>()
                    response.body()!!.vehicles.forEach { v ->
                        database.vehicleDao().deleteImagesForVehicle(v.id)
                        v.images?.forEach { img ->
                            allImages.add(VehicleImageEntity(
                                id = img.id ?: java.util.UUID.randomUUID().toString(),
                                vehicleId = v.id,
                                imageUrl = img.imageUrl ?: "",
                                sortOrder = img.sortOrder ?: 0
                            ))
                        }
                        if (v.images == null && !v.imageUrl.isNullOrBlank()) {
                            v.imageUrl.split(",").map { it.trim() }.filter { it.isNotBlank() }.forEachIndexed { index, url ->
                                allImages.add(VehicleImageEntity(
                                    vehicleId = v.id,
                                    imageUrl = url,
                                    sortOrder = index
                                ))
                            }
                        }
                    }
                    if (allImages.isNotEmpty()) {
                        database.vehicleDao().insertVehicleImages(allImages)
                    }
                }
                Result.success(list)
            } else {
                Result.failure(Exception("Erreur serveur véhicules: ${response.code()}"))
            }
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    suspend fun refreshRentals(): Result<List<Reservation>> = withContext(Dispatchers.IO) {
        try {
            val response = apiClient.getService().getRentals(page = 1, pageSize = 100)
            if (response.isSuccessful && response.body() != null) {
                val list = response.body()!!.rentals.map { mapRentalDtoToDomain(it) }
                val entities = list.map { ReservationEntity.fromDomain(it) }
                database.withTransaction {
                    database.reservationDao().clearAll()
                    database.reservationDao().insertReservations(entities)
                }
                Result.success(list)
            } else {
                Result.failure(Exception("Erreur serveur réservations: ${response.code()}"))
            }
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    suspend fun refreshMaintenances(): Result<List<MaintenanceTicket>> = withContext(Dispatchers.IO) {
        try {
            val response = apiClient.getService().getMaintenances(page = 1, size = 100)
            if (response.isSuccessful && response.body() != null) {
                val list = response.body()!!.items.map { mapMaintenanceDtoToDomain(it) }
                val entities = list.map { MaintenanceEntity.fromDomain(it) }
                database.withTransaction {
                    database.maintenanceDao().clearAll()
                    database.maintenanceDao().insertTickets(entities)
                }
                Result.success(list)
            } else {
                Result.failure(Exception("Erreur serveur maintenance: ${response.code()}"))
            }
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
     * Refreshes all entities. If never bootstrapped, executes initial bootstrap.
     */
    suspend fun refreshAll(): Result<Unit> = withContext(Dispatchers.IO) {
        val isBootstrapped = database.syncMetadataDao().getValue("is_bootstrapped") == "true"
        Log.i("SYNC", "[SYNC] refreshAll START (isBootstrapped=$isBootstrapped)")
        if (!isBootstrapped) {
            return@withContext bootstrapAndReset()
        }

        _syncStatus.value = _syncStatus.value.copy(
            state = SyncStatusState.SYNCING,
            message = "Synchronisation des données..."
        )

        val rVehicles = refreshVehicles()
        val rRentals = refreshRentals()
        val rMaint = refreshMaintenances()
        val rDash = refreshDashboard()
        val rNotifs = refreshNotifications()

        if (rVehicles.isSuccess || rRentals.isSuccess || rMaint.isSuccess) {
            val syncTime = getCurrentTimeString()
            database.syncMetadataDao().setValue(SyncMetadataEntity("last_sync_at", syncTime))
            _syncStatus.value = SyncStatus(
                state = SyncStatusState.SYNCED,
                message = "Synchronisation terminée",
                lastSyncTime = syncTime,
                isBootstrapped = true,
                errorMessage = null
            )
            Log.i("SYNC", "[SYNC] refreshAll SUCCESS")
            Result.success(Unit)
        } else {
            val errMsg = rVehicles.exceptionOrNull()?.message ?: "Erreur de synchronisation"
            val ex = rVehicles.exceptionOrNull() ?: Exception("Unknown error")
            Log.e("SYNC", "SYNC FAILED\ntype=NETWORK\nendpoint=/api/v1/*\nstatus=0\nmessage=$errMsg", ex)
            _syncStatus.value = _syncStatus.value.copy(
                state = SyncStatusState.SYNC_ERROR,
                message = "Synchronisation échouée",
                errorMessage = errMsg
            )
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
