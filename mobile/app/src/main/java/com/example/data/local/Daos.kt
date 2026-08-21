package com.example.data.local

import androidx.room.*
import kotlinx.coroutines.flow.Flow

@Dao
interface VehicleDao {
    @Query("SELECT * FROM vehicles ORDER BY brand ASC, modelName ASC")
    fun getAllVehicles(): Flow<List<VehicleEntity>>

    @Transaction
    @Query("SELECT * FROM vehicles WHERE id = :id")
    suspend fun getVehicleWithImages(id: String): VehicleWithImages?

    @Query("SELECT * FROM vehicles WHERE id = :id")
    suspend fun getVehicleById(id: String): VehicleEntity?

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insertVehicleImages(images: List<VehicleImageEntity>)

    @Query("DELETE FROM vehicle_images WHERE vehicleId = :vehicleId")
    suspend fun deleteImagesForVehicle(vehicleId: String)


    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insertVehicles(vehicles: List<VehicleEntity>)

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insertVehicle(vehicle: VehicleEntity)

    @Query("UPDATE vehicles SET status = :status WHERE id = :id")
    suspend fun updateVehicleStatus(id: String, status: String)

    @Query("DELETE FROM vehicles WHERE id = :id")
    suspend fun deleteVehicle(id: String)

    @Query("DELETE FROM vehicles")
    suspend fun clearAll()
}

@Dao
interface ReservationDao {
    @Query("SELECT * FROM reservations ORDER BY startDate DESC")
    fun getAllReservations(): Flow<List<ReservationEntity>>

    @Query("SELECT * FROM reservations WHERE id = :id")
    suspend fun getReservationById(id: String): ReservationEntity?

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insertReservations(reservations: List<ReservationEntity>)

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insertReservation(reservation: ReservationEntity)

    @Query("UPDATE reservations SET status = :status, lastUpdated = :lastUpdated WHERE id = :id")
    suspend fun updateReservationStatus(id: String, status: String, lastUpdated: String)

    @Query("DELETE FROM reservations WHERE id = :id")
    suspend fun deleteReservation(id: String)

    @Query("DELETE FROM reservations")
    suspend fun clearAll()
}

@Dao
interface MaintenanceDao {
    @Query("SELECT * FROM maintenance ORDER BY scheduledDate DESC")
    fun getAllTickets(): Flow<List<MaintenanceEntity>>

    @Query("SELECT * FROM maintenance WHERE id = :id")
    suspend fun getTicketById(id: String): MaintenanceEntity?

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insertTickets(tickets: List<MaintenanceEntity>)

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insertTicket(ticket: MaintenanceEntity)

    @Query("UPDATE maintenance SET step = :step WHERE id = :id")
    suspend fun updateTicketStep(id: String, step: String)

    @Query("UPDATE maintenance SET status = :status WHERE id = :id")
    suspend fun updateTicketStatus(id: String, status: String)

    @Query("DELETE FROM maintenance WHERE id = :id")
    suspend fun deleteTicket(id: String)

    @Query("DELETE FROM maintenance")
    suspend fun clearAll()
}

@Dao
interface NotificationDao {
    @Query("SELECT * FROM notifications ORDER BY createdAt DESC")
    fun getAllNotifications(): Flow<List<NotificationEntity>>

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insertNotifications(notifications: List<NotificationEntity>)

    @Query("UPDATE notifications SET isRead = 1 WHERE id = :id")
    suspend fun markAsRead(id: String)

    @Query("UPDATE notifications SET isRead = 1")
    suspend fun markAllAsRead()

    @Query("DELETE FROM notifications")
    suspend fun clearAll()
}

@Dao
interface SyncMetadataDao {
    @Query("SELECT value FROM sync_metadata WHERE `key` = :key")
    suspend fun getValue(key: String): String?

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun setValue(metadata: SyncMetadataEntity)

    @Query("DELETE FROM sync_metadata WHERE `key` = :key")
    suspend fun deleteKey(key: String)

    @Query("DELETE FROM sync_metadata")
    suspend fun clearAll()
}
