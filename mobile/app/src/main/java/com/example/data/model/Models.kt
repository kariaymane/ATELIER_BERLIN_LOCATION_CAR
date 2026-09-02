package com.example.data.model

enum class VehicleStatus(val label: String, val apiValue: String) {
    DISPONIBLE("Disponible", "AVAILABLE"),
    EN_LOCATION("En location", "RENTED"),
    RESERVEE("Réservé", "RESERVED"),
    MAINTENANCE("Maintenance", "MAINTENANCE"),
    VENDU("Vendu", "SOLD"),
    INACTIF("Inactif", "INACTIVE");

    companion object {
        /**
         * Canonical backend/shared status token -> UI enum. STRUCTURAL states
         * (SOLD / INACTIVE) must NOT collapse to DISPONIBLE — that let a sold
         * or retired vehicle read as bookable (forensic P2). An absent value
         * follows the backend default (AVAILABLE); an unrecognised token is
         * treated as INACTIF so it can never silently present as available.
         */
        fun fromApi(value: String?): VehicleStatus {
            return when (value?.trim()?.uppercase()) {
                "AVAILABLE", "DISPONIBLE" -> DISPONIBLE
                "RENTED", "EN_LOCATION", "ACTIVE" -> EN_LOCATION
                "RESERVED", "RESERVEE" -> RESERVEE
                "MAINTENANCE" -> MAINTENANCE
                "SOLD", "VENDU" -> VENDU
                "INACTIVE", "INACTIF" -> INACTIF
                null, "" -> DISPONIBLE
                else -> INACTIF
            }
        }
    }
}

enum class VehicleCategory(val label: String) {
    ALL("Tous"),
    DISPONIBLE("Disponible"),
    EN_LOCATION("En location"),
    MAINTENANCE("Maintenance")
}

data class Vehicle(
    val id: String,
    val brand: String,
    val modelName: String,
    val plate: String,
    val year: Int,
    val category: String = "Berline",
    val dailyRate: Int,
    val status: VehicleStatus,
    val mileage: Int = 0,
    val fuelType: String = "",
    val transmission: String = "",
    val power: String = "",
    val color: String = "",
    val imageUrl: String = "",
    val images: List<String> = emptyList(),
    val description: String = "",
    val vin: String = "",
    val deposit: Int = 0,
    val version: Int = 1
) {
    val fullName: String get() = "$brand $modelName"
}

enum class ReservationStatus(val label: String, val apiValue: String) {
    RESERVEE("Réservée", "RESERVED"),
    EN_COURS("En cours", "ACTIVE"),
    TERMINEE("Terminée", "COMPLETED"),
    ANNULEE("Annulée", "CANCELLED");

    companion object {
        fun fromApi(value: String?): ReservationStatus {
            return when (value?.uppercase()) {
                "RESERVED", "RESERVEE" -> RESERVEE
                "ACTIVE", "EN_COURS" -> EN_COURS
                "COMPLETED", "TERMINEE" -> TERMINEE
                "CANCELLED", "ANNULEE" -> ANNULEE
                else -> RESERVEE
            }
        }
    }
}

data class Reservation(
    val id: String,
    val clientName: String,
    val clientPhone: String = "",
    val clientEmail: String = "",
    val identityCardImage: String = "",
    val drivingLicenseImage: String = "",
    val vehicleId: String,
    val vehicleName: String,
    val vehiclePlate: String,
    val vehicleImageUrl: String = "",
    val startDate: String,
    val endDate: String,
    val status: ReservationStatus,
    val totalAmount: Int,
    val dailyPrice: Int = 0,
    val numDays: Int = 0,
    val deposit: Int = 0,
    val paymentStatus: String = "PAYÉ",
    val lastUpdated: String = "À l'instant",
    val pickupLocation: String = "",
    val returnLocation: String = "",
    val notes: String = "",
    // Raw ISO-8601 UTC interval edges (machine-parseable; `startDate`/`endDate`
    // are the localized display strings).
    val startIso: String = "",
    val endIso: String = ""
)

enum class MaintenanceStep(val label: String, val order: Int) {
    EN_ATTENTE("En attente", 0),
    DIAGNOSTIC("Diagnostic", 1),
    REPARATION("Réparation", 2),
    CONTROLE("Contrôle", 3),
    TERMINEE("Terminé", 4);

    companion object {
        fun fromApi(value: String?): MaintenanceStep {
            return when (value?.uppercase()?.replace("_", " ")) {
                "DIAGNOSTIC", "DIAG" -> DIAGNOSTIC
                "REPARATION", "RÉPARATION" -> REPARATION
                "CONTROLE", "CONTRÔLE", "TESTS" -> CONTROLE
                "TERMINEE", "TERMINÉ", "FINALISÉ", "COMPLETED" -> TERMINEE
                else -> EN_ATTENTE
            }
        }
    }
}

data class MaintenancePart(
    val id: String? = null,
    val part_name: String,
    val quantity: Double = 1.0,
    val unit_price: Double = 0.0,
    val total_price: Double = 0.0,
    val notes: String? = null
)

data class MaintenanceTicket(
    val id: String,
    val vehicleId: String,
    val vehicleName: String = "",
    val vehiclePlate: String = "",
    val serviceItem: String = "Entretien", // Maps to type
    val title: String? = null,
    val description: String = "",
    val diagnosis: String? = null,
    val repair_description: String? = null,
    val scheduledDate: String = "", // Maps to start_datetime
    val expected_end_datetime: String? = null,
    val actual_end_datetime: String? = null,
    val mileage: Double? = null,
    val location: String? = null,
    val technician: String = "", // Maps to technician_name
    val invoice_number: String? = null,
    val oil_brand: String? = null,
    val oil_viscosity: String? = null,
    val oil_quantity: Double? = null,
    val oil_filter_changed: Boolean = false,
    val air_filter_changed: Boolean = false,
    val fuel_filter_changed: Boolean = false,
    val cabin_filter_changed: Boolean = false,
    val estimatedCost: Int = 0, // Maps to estimated_cost (or double)
    val parts_cost: Double = 0.0,
    val labor_cost: Double = 0.0,
    val other_cost: Double = 0.0,
    val actual_cost: Double? = null, // Maps to total_cost
    val next_maintenance_date: String? = null,
    val next_maintenance_mileage: Double? = null,
    val step: MaintenanceStep = MaintenanceStep.DIAGNOSTIC,
    val status: String = "ACTIVE",
    val priority: String = "Haute",
    val notes: String = "",
    val parts: List<MaintenancePart> = emptyList(),
    // Raw ISO-8601 UTC start (machine-parseable; `scheduledDate` is display).
    val startIso: String? = null
)

data class PerformanceMetrics(
    val todayBookings: Int,
    val weekBookings: Int,
    val monthBookings: Int,
    val yearBookings: Int = 0,
    val todayRevenue: Double,
    val weekRevenue: Double,
    val monthRevenue: Double,
    val yearRevenue: Double = 0.0,
    val readyVehicles: Int,
    val rentedVehicles: Int,
    val reservedVehicles: Int,
    val maintenanceVehicles: Int
)

data class UserSession(
    val id: String,
    val email: String,
    val name: String,
    val role: String,
    val token: String,
    val initials: String = "SE"
)

data class NotificationItem(
    val id: String,
    val vehicleId: String? = null,
    val vehicleName: String? = null,
    val vehiclePlate: String? = null,
    val type: String = "ALERT",
    val severity: String = "warning",
    val title: String = "",
    val message: String = "",
    val dueDate: String? = null,
    val isRead: Boolean = false,
    val createdAt: String? = null
)

enum class SyncStatusState(val label: String) {
    DISCONNECTED("Déconnecté"),
    CONNECTING("Connexion au logiciel..."),
    CONNECTED("Connecté"),
    RESETTING("Réinitialisation des données locales..."),
    SYNCING("Synchronisation des données..."),
    SYNCED("Synchronisation terminée"),
    REALTIME_ACTIVE("En direct (Temps réel)"),
    SYNC_ERROR("Erreur de synchronisation"),

    /** Server was reached, but its database is temporarily unavailable
     *  (readiness probe returned 503). Cached data is still shown; this is a
     *  transient backend condition, NOT a dead session and NOT "unreachable". */
    SERVER_DB_UNAVAILABLE("Base de données du serveur indisponible")
}

/**
 * How the last sync attempt classified backend availability. Lets the UI tell
 * "app is offline" apart from "server up but its DB is down" apart from "live".
 */
enum class ServerReachability {
    /** Not probed yet this session. */
    UNKNOWN,
    /** Reachable AND its database answered `SELECT 1`. */
    ONLINE,
    /** Reachable but the database is unavailable (readiness 503). */
    DATABASE_DOWN,
    /** Could not be reached at all (DNS / connect / timeout). */
    UNREACHABLE
}

data class SyncStatus(
    val state: SyncStatusState = SyncStatusState.DISCONNECTED,
    val message: String = "Déconnecté",
    val lastSyncTime: String? = null,
    val serverId: String? = null,
    val isBootstrapped: Boolean = false,
    val isRealtimeConnected: Boolean = false,
    val errorMessage: String? = null,
    val reachability: ServerReachability = ServerReachability.UNKNOWN
) {
    /**
     * True when the screen is showing LOCAL (Room) data that is not being kept
     * live right now — a full-screen fatal error must not be used in this
     * state if any cached rows exist; show an offline banner instead.
     */
    val isShowingStaleData: Boolean
        get() = state == SyncStatusState.SYNC_ERROR ||
            state == SyncStatusState.SERVER_DB_UNAVAILABLE ||
            state == SyncStatusState.DISCONNECTED

    /** The server is up but its database is down (distinct from unreachable). */
    val isServerDatabaseDown: Boolean
        get() = state == SyncStatusState.SERVER_DB_UNAVAILABLE ||
            reachability == ServerReachability.DATABASE_DOWN
}
