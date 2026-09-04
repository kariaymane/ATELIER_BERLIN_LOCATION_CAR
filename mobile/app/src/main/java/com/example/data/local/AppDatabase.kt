package com.example.data.local

import android.content.Context
import androidx.room.Database
import androidx.room.Room
import androidx.room.RoomDatabase

@Database(
    entities = [
        VehicleEntity::class,
        VehicleImageEntity::class,
        ReservationEntity::class,
        MaintenanceEntity::class,
        MaintenancePartEntity::class,
        NotificationEntity::class,
        SyncMetadataEntity::class
    ],
    // v10 — ReservationEntity gains `cancellationReason` + `cancelledAtIso` so
    // the offline revenue engine can preserve the days realised before a
    // maintenance interruption (parity with backend/desktop). Schema change +
    // `fallbackToDestructiveMigration` wipes the local mirror on first launch;
    // Room then re-runs a clean INITIAL bootstrap from FastAPI/PostgreSQL.
    // CACHE reset only — never touches the authoritative PostgreSQL data.
    version = 10,
    exportSchema = false
)
abstract class AppDatabase : RoomDatabase() {
    abstract fun vehicleDao(): VehicleDao
    abstract fun reservationDao(): ReservationDao
    abstract fun maintenanceDao(): MaintenanceDao
    abstract fun notificationDao(): NotificationDao
    abstract fun syncMetadataDao(): SyncMetadataDao

    companion object {
        @Volatile
        private var INSTANCE: AppDatabase? = null

        fun getDatabase(context: Context): AppDatabase {
            return INSTANCE ?: synchronized(this) {
                val instance = Room.databaseBuilder(
                    context.applicationContext,
                    AppDatabase::class.java,
                    "soft_executive_fleet_v2.db"
                )
                .fallbackToDestructiveMigration(true)
                .build()
                INSTANCE = instance
                instance
            }
        }
    }
}
