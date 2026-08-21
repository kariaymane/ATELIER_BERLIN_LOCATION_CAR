package com.example.data.local

import androidx.room.Entity
import androidx.room.ForeignKey
import androidx.room.PrimaryKey
import androidx.room.Index
import com.example.data.model.*

@Entity(tableName = "vehicles")
data class VehicleEntity(
    @PrimaryKey val id: String,
    val brand: String,
    val modelName: String,
    val plate: String,
    val year: Int,
    val category: String,
    val dailyRate: Int,
    val status: String,
    val mileage: Int,
    val fuelType: String,
    val transmission: String,
    val power: String,
    val color: String,
    val imageUrl: String,
    val imagesList: String = "",
    val description: String,
    val vin: String,
    val deposit: Int
) {
    fun toDomain() = Vehicle(id, brand, modelName, plate, year, category, dailyRate, VehicleStatus.fromApi(status), mileage, fuelType, transmission, power, color, imageUrl, imagesList.split(",").filter { it.isNotBlank() }, description, vin, deposit)
    companion object { fun fromDomain(v: Vehicle) = VehicleEntity(v.id, v.brand, v.modelName, v.plate, v.year, v.category, v.dailyRate, v.status.apiValue, v.mileage, v.fuelType, v.transmission, v.power, v.color, v.imageUrl, v.images.joinToString(","), v.description, v.vin, v.deposit) }
}

@Entity(tableName = "reservations")
data class ReservationEntity(
    @PrimaryKey val id: String,
    val clientName: String,
    val clientPhone: String,
    val clientEmail: String,
    val vehicleId: String,
    val vehicleName: String,
    val vehiclePlate: String,
    val vehicleImageUrl: String,
    val startDate: String,
    val endDate: String,
    val status: String,
    val totalAmount: Int,
    val dailyPrice: Int,
    val numDays: Int,
    val deposit: Int,
    val paymentStatus: String,
    val lastUpdated: String,
    val pickupLocation: String,
    val returnLocation: String,
    val notes: String
) {
    fun toDomain() = Reservation(id, clientName, clientPhone, clientEmail, vehicleId, vehicleName, vehiclePlate, vehicleImageUrl, startDate, endDate, ReservationStatus.fromApi(status), totalAmount, dailyPrice, numDays, deposit, paymentStatus, lastUpdated, pickupLocation, returnLocation, notes)
    companion object { fun fromDomain(r: Reservation) = ReservationEntity(r.id, r.clientName, r.clientPhone, r.clientEmail, r.vehicleId, r.vehicleName, r.vehiclePlate, r.vehicleImageUrl, r.startDate, r.endDate, r.status.apiValue, r.totalAmount, r.dailyPrice, r.numDays, r.deposit, r.paymentStatus, r.lastUpdated, r.pickupLocation, r.returnLocation, r.notes) }
}

@Entity(tableName = "maintenance")
data class MaintenanceEntity(
    @PrimaryKey val id: String,
    val vehicleId: String,
    val vehicleName: String,
    val vehiclePlate: String,
    val serviceItem: String,
    val title: String? = null,
    val description: String,
    val diagnosis: String? = null,
    val repair_description: String? = null,
    val scheduledDate: String,
    val expected_end_datetime: String? = null,
    val actual_end_datetime: String? = null,
    val mileage: Double? = null,
    val location: String? = null,
    val technician: String,
    val invoice_number: String? = null,
    val oil_brand: String? = null,
    val oil_viscosity: String? = null,
    val oil_quantity: Double? = null,
    val oil_filter_changed: Boolean = false,
    val air_filter_changed: Boolean = false,
    val fuel_filter_changed: Boolean = false,
    val cabin_filter_changed: Boolean = false,
    val estimatedCost: Int,
    val parts_cost: Double = 0.0,
    val labor_cost: Double = 0.0,
    val other_cost: Double = 0.0,
    val actual_cost: Double? = null,
    val next_maintenance_date: String? = null,
    val next_maintenance_mileage: Double? = null,
    val step: String,
    val status: String,
    val priority: String,
    val notes: String
) {
    fun toDomain() = MaintenanceTicket(id, vehicleId, vehicleName, vehiclePlate, serviceItem, title, description, diagnosis, repair_description, scheduledDate, expected_end_datetime, actual_end_datetime, mileage, location, technician, invoice_number, oil_brand, oil_viscosity, oil_quantity, oil_filter_changed, air_filter_changed, fuel_filter_changed, cabin_filter_changed, estimatedCost, parts_cost, labor_cost, other_cost, actual_cost, next_maintenance_date, next_maintenance_mileage, MaintenanceStep.fromApi(step), status, priority, notes)
    companion object { fun fromDomain(m: MaintenanceTicket) = MaintenanceEntity(m.id, m.vehicleId, m.vehicleName, m.vehiclePlate, m.serviceItem, m.title, m.description, m.diagnosis, m.repair_description, m.scheduledDate, m.expected_end_datetime, m.actual_end_datetime, m.mileage, m.location, m.technician, m.invoice_number, m.oil_brand, m.oil_viscosity, m.oil_quantity, m.oil_filter_changed, m.air_filter_changed, m.fuel_filter_changed, m.cabin_filter_changed, m.estimatedCost, m.parts_cost, m.labor_cost, m.other_cost, m.actual_cost, m.next_maintenance_date, m.next_maintenance_mileage, m.step.label, m.status, m.priority, m.notes) }
}

@Entity(
    tableName = "maintenance_parts",
    foreignKeys = [
        ForeignKey(
            entity = MaintenanceEntity::class,
            parentColumns = ["id"],
            childColumns = ["maintenanceId"],
            onDelete = ForeignKey.CASCADE
        )
    ],
    indices = [Index("maintenanceId")]
)
data class MaintenancePartEntity(
    @PrimaryKey val id: String,
    val maintenanceId: String,
    val part_name: String,
    val quantity: Double,
    val unit_price: Double,
    val total_price: Double,
    val notes: String?
)

@Entity(tableName = "notifications")
data class NotificationEntity(
    @PrimaryKey val id: String,
    val vehicleId: String?,
    val vehicleName: String?,
    val vehiclePlate: String?,
    val type: String,
    val severity: String,
    val title: String,
    val message: String,
    val dueDate: String?,
    val isRead: Boolean,
    val createdAt: String?
) {
    fun toDomain() = NotificationItem(id, vehicleId, vehicleName, vehiclePlate, type, severity, title, message, dueDate, isRead, createdAt)
    companion object { fun fromDomain(n: NotificationItem) = NotificationEntity(n.id, n.vehicleId, n.vehicleName, n.vehiclePlate, n.type, n.severity, n.title, n.message, n.dueDate, n.isRead, n.createdAt) }
}

@Entity(tableName = "sync_metadata")
data class SyncMetadataEntity(
    @PrimaryKey val key: String,
    val value: String,
    val updatedAt: Long = System.currentTimeMillis()
)
