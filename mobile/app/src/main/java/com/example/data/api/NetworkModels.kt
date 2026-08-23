package com.example.data.api

import com.squareup.moshi.Json
import com.squareup.moshi.JsonClass


@JsonClass(generateAdapter = true)
data class VehicleImageDto(
    @Json(name = "id") val id: String? = null,
    @Json(name = "image_url") val imageUrl: String? = null,
    @Json(name = "sort_order") val sortOrder: Int? = 0
)

@JsonClass(generateAdapter = true)
data class LoginRequestDto(
    @Json(name = "email") val email: String,
    @Json(name = "password") val password: String,
    @Json(name = "device_id") val deviceId: String? = "android_mobile"
)

@JsonClass(generateAdapter = true)
data class UserDto(
    @Json(name = "id") val id: String,
    @Json(name = "email") val email: String,
    @Json(name = "first_name") val firstName: String? = null,
    @Json(name = "last_name") val lastName: String? = null,
    @Json(name = "role") val role: String,
    @Json(name = "language") val language: String? = "fr"
)

@JsonClass(generateAdapter = true)
data class LoginResponseDto(
    @Json(name = "access_token") val accessToken: String,
    @Json(name = "refresh_token") val refreshToken: String? = null,
    @Json(name = "token_type") val tokenType: String = "bearer",
    @Json(name = "user_id") val userId: String? = null,
    @Json(name = "role") val role: String? = null,
    @Json(name = "full_name") val fullName: String? = null,
    @Json(name = "user") val user: UserDto? = null
)

@JsonClass(generateAdapter = true)
data class RefreshRequestDto(
    @Json(name = "refresh_token") val refreshToken: String
)

@JsonClass(generateAdapter = true)
data class RefreshResponseDto(
    @Json(name = "access_token") val accessToken: String,
    @Json(name = "refresh_token") val refreshToken: String,
    @Json(name = "token_type") val tokenType: String = "bearer"
)

@JsonClass(generateAdapter = true)
data class VehicleDto(
    @Json(name = "id") val id: String,
    @Json(name = "registration") val registration: String,
    @Json(name = "vin") val vin: String? = null,
    @Json(name = "brand") val brand: String,
    @Json(name = "model") val model: String,
    @Json(name = "year") val year: Int,
    @Json(name = "color") val color: String? = null,
    @Json(name = "fuel_type") val fuelType: String? = null,
    @Json(name = "transmission") val transmission: String? = null,
    @Json(name = "current_mileage") val currentMileage: Int = 0,
    @Json(name = "daily_rental_price") val dailyRentalPrice: Double = 0.0,
    @Json(name = "status") val status: String = "AVAILABLE",
    @Json(name = "notes") val notes: String? = null,
    @Json(name = "image_url") val imageUrl: String? = null,
    @Json(name = "images") val images: List<VehicleImageDto>? = null,
    @Json(name = "version") val version: Int = 1
)

@JsonClass(generateAdapter = true)
data class VehicleListResponseDto(
    @Json(name = "vehicles") val vehicles: List<VehicleDto> = emptyList(),
    @Json(name = "total") val total: Int = 0,
    @Json(name = "page") val page: Int = 1,
    @Json(name = "page_size") val pageSize: Int = 25
)

@JsonClass(generateAdapter = true)
data class VehicleStatusUpdateDto(
    @Json(name = "status") val status: String
)

@JsonClass(generateAdapter = true)
data class RentalDto(
    @Json(name = "id") val id: String,
    @Json(name = "vehicle_id") val vehicleId: String,
    @Json(name = "customer_name") val customerName: String? = null,
    @Json(name = "customer_phone") val customerPhone: String? = null,
    @Json(name = "customer_email") val customerEmail: String? = null,
    @Json(name = "identity_card_image") val identityCardImage: String? = null,
    @Json(name = "driving_license_image") val drivingLicenseImage: String? = null,
    @Json(name = "start_datetime") val startDatetime: String,
    @Json(name = "end_datetime") val endDatetime: String,
    @Json(name = "daily_price") val dailyPrice: Double = 0.0,
    @Json(name = "num_days") val numDays: Int = 1,
    @Json(name = "total_price") val totalPrice: Double = 0.0,
    @Json(name = "deposit") val deposit: Double = 0.0,
    @Json(name = "payment_status") val paymentStatus: String = "PENDING",
    @Json(name = "status") val status: String = "RESERVED",
    @Json(name = "notes") val notes: String? = null,
    @Json(name = "vehicle_registration") val vehicleRegistration: String? = null,
    @Json(name = "vehicle_brand") val vehicleBrand: String? = null,
    @Json(name = "vehicle_model") val vehicleModel: String? = null
)

@JsonClass(generateAdapter = true)
data class RentalListResponseDto(
    @Json(name = "rentals") val rentals: List<RentalDto> = emptyList(),
    @Json(name = "total") val total: Int = 0,
    @Json(name = "page") val page: Int = 1,
    @Json(name = "page_size") val pageSize: Int = 25
)

@JsonClass(generateAdapter = true)
data class RentalCreateDto(
    @Json(name = "vehicle_id") val vehicleId: String,
    @Json(name = "customer_name") val customerName: String,
    @Json(name = "customer_phone") val customerPhone: String,
    @Json(name = "customer_email") val customerEmail: String? = null,
    @Json(name = "identity_card_image") val identityCardImage: String? = null,
    @Json(name = "driving_license_image") val drivingLicenseImage: String? = null,
    @Json(name = "start_datetime") val startDatetime: String,
    @Json(name = "end_datetime") val endDatetime: String,
    @Json(name = "daily_price") val dailyPrice: Double? = null,
    @Json(name = "deposit") val deposit: Double? = 0.0,
    @Json(name = "notes") val notes: String? = null
)

@JsonClass(generateAdapter = true)
data class MaintenancePartDto(
    @Json(name = "id") val id: String? = null,
    @Json(name = "part_name") val partName: String,
    @Json(name = "quantity") val quantity: Double = 1.0,
    @Json(name = "unit_price") val unitPrice: Double = 0.0,
    @Json(name = "total_price") val totalPrice: Double = 0.0,
    @Json(name = "notes") val notes: String? = null
)

data class MaintenanceDto(
    @Json(name = "id") val id: String,
    @Json(name = "vehicle_id") val vehicleId: String,
    @Json(name = "type") val type: String = "ENTRETIEN",
    @Json(name = "title") val title: String? = null,
    @Json(name = "description") val description: String? = null,
    @Json(name = "diagnosis") val diagnosis: String? = null,
    @Json(name = "repair_description") val repairDescription: String? = null,
    @Json(name = "start_datetime") val startDatetime: String? = null,
    @Json(name = "expected_end_datetime") val expectedEndDatetime: String? = null,
    @Json(name = "actual_end_datetime") val actualEndDatetime: String? = null,
    @Json(name = "mileage") val mileage: Double? = null,
    @Json(name = "location") val location: String? = null,
    @Json(name = "technician_name") val technicianName: String? = null,
    @Json(name = "invoice_number") val invoiceNumber: String? = null,
    @Json(name = "oil_brand") val oilBrand: String? = null,
    @Json(name = "oil_viscosity") val oilViscosity: String? = null,
    @Json(name = "oil_quantity") val oilQuantity: Double? = null,
    @Json(name = "oil_filter_changed") val oilFilterChanged: Boolean = false,
    @Json(name = "air_filter_changed") val airFilterChanged: Boolean = false,
    @Json(name = "fuel_filter_changed") val fuelFilterChanged: Boolean = false,
    @Json(name = "cabin_filter_changed") val cabinFilterChanged: Boolean = false,
    @Json(name = "estimated_cost") val estimatedCost: Double? = null,
    @Json(name = "parts_cost") val partsCost: Double = 0.0,
    @Json(name = "labor_cost") val laborCost: Double = 0.0,
    @Json(name = "other_cost") val otherCost: Double = 0.0,
    @Json(name = "actual_cost") val actualCost: Double? = null,
    @Json(name = "next_maintenance_date") val nextMaintenanceDate: String? = null,
    @Json(name = "next_maintenance_mileage") val nextMaintenanceMileage: Double? = null,
    @Json(name = "step") val step: String = "EN ATTENTE",
    @Json(name = "status") val status: String = "ACTIVE",
    @Json(name = "notes") val notes: String? = null,
    @Json(name = "vehicle_brand") val vehicleBrand: String? = null,
    @Json(name = "vehicle_model") val vehicleModel: String? = null,
    @Json(name = "vehicle_registration") val vehicleRegistration: String? = null,
    @Json(name = "vehicle_image_url") val vehicleImageUrl: String? = null,
    @Json(name = "parts") val parts: List<MaintenancePartDto> = emptyList()
)

@JsonClass(generateAdapter = true)
data class MaintenanceListResponseDto(
    @Json(name = "items") val items: List<MaintenanceDto> = emptyList(),
    @Json(name = "total") val total: Int = 0,
    @Json(name = "page") val page: Int = 1,
    @Json(name = "size") val size: Int = 20,
    @Json(name = "pages") val pages: Int = 1
)

@JsonClass(generateAdapter = true)
data class MaintenanceCreateDto(
    @Json(name = "vehicle_id") val vehicleId: String,
    @Json(name = "type") val type: String,
    @Json(name = "description") val description: String? = null,
    @Json(name = "start_datetime") val startDatetime: String,
    @Json(name = "expected_end_datetime") val expectedEndDatetime: String? = null,
    @Json(name = "estimated_cost") val estimatedCost: Double? = null,
    @Json(name = "location") val location: String? = null,
    @Json(name = "step") val step: String = "DIAGNOSTIC",
    @Json(name = "status") val status: String = "ACTIVE",
    @Json(name = "notes") val notes: String? = null
)

@JsonClass(generateAdapter = true)
data class DashboardStatsDto(
    @Json(name = "total_vehicles") val totalVehicles: Int = 0,
    @Json(name = "available") val available: Int = 0,
    @Json(name = "reserved") val reserved: Int = 0,
    @Json(name = "rented") val rented: Int = 0,
    @Json(name = "maintenance") val maintenance: Int = 0,
    @Json(name = "active_maintenance_tickets") val activeMaintenanceTickets: Int = 0,
    @Json(name = "active_rentals") val activeRentals: Int = 0,
    @Json(name = "reserved_rentals") val reservedRentals: Int = 0,
    @Json(name = "today_rentals") val todayRentals: Int = 0,
    @Json(name = "today_returns") val todayReturns: Int = 0,
    @Json(name = "today_revenue") val todayRevenue: Double = 0.0,
    @Json(name = "week_rentals") val weekRentals: Int = 0,
    @Json(name = "week_revenue") val weekRevenue: Double = 0.0,
    @Json(name = "month_rentals") val monthRentals: Int = 0,
    @Json(name = "month_revenue") val monthRevenue: Double = 0.0
)

@JsonClass(generateAdapter = true)
data class NotificationDto(
    @Json(name = "id") val id: String,
    @Json(name = "vehicle_id") val vehicleId: String? = null,
    @Json(name = "vehicle_name") val vehicleName: String? = null,
    @Json(name = "vehicle_registration") val vehicleRegistration: String? = null,
    @Json(name = "type") val type: String = "ALERT",
    @Json(name = "severity") val severity: String = "warning",
    @Json(name = "title") val title: String = "",
    @Json(name = "message") val message: String = "",
    @Json(name = "due_date") val dueDate: String? = null,
    @Json(name = "is_read") val isRead: Boolean = false,
    @Json(name = "created_at") val createdAt: String? = null
)

@JsonClass(generateAdapter = true)
data class NotificationListResponseDto(
    @Json(name = "items") val items: List<NotificationDto> = emptyList(),
    @Json(name = "total") val total: Int = 0,
    @Json(name = "unread_count") val unreadCount: Int = 0,
    @Json(name = "page") val page: Int = 1,
    @Json(name = "page_size") val pageSize: Int = 50
)

@JsonClass(generateAdapter = true)
data class SyncHealthResponseDto(
    @Json(name = "status") val status: String = "healthy",
    @Json(name = "version") val version: String = "1.0.0",
    @Json(name = "api_version") val apiVersion: String? = "1.0.0",
    @Json(name = "server_id") val serverId: String? = "car-rental-server-v1"
)

@JsonClass(generateAdapter = true)
data class SyncBootstrapResponseDto(
    @Json(name = "sync_version") val syncVersion: Int = 1,
    @Json(name = "server_time") val serverTime: String,
    @Json(name = "server_id") val serverId: String = "car-rental-server-v1",
    @Json(name = "api_version") val apiVersion: String = "1.0.0",
    @Json(name = "vehicles") val vehicles: List<VehicleDto> = emptyList(),
    @Json(name = "rentals") val rentals: List<RentalDto> = emptyList(),
    @Json(name = "maintenance") val maintenance: List<MaintenanceDto> = emptyList(),
    @Json(name = "notifications") val notifications: List<NotificationDto> = emptyList()
)

@JsonClass(generateAdapter = true)
data class WebSocketEventDto(
    @Json(name = "event_type") val eventType: String? = null,
    @Json(name = "type") val type: String? = null,
    @Json(name = "entity_type") val entityType: String? = null,
    @Json(name = "entity") val entity: String? = null,
    @Json(name = "entity_id") val entityId: String? = null,
    @Json(name = "message") val message: String? = null,
    @Json(name = "origin") val origin: String? = null,
    @Json(name = "vehicle_id") val vehicleId: String? = null,
    @Json(name = "vehicle_registration") val vehicleRegistration: String? = null,
    @Json(name = "timestamp") val timestamp: String? = null
)
