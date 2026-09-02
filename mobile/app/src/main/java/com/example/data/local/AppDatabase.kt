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
    // v9 — forced one-time cache reset for the dashboard-live-sync release.
    // Schema is unchanged; the bump exists only so `fallbackToDestructiveMigration`
    // wipes any stale local mirror (obsolete dashboard/sync-metadata/notification
    // rows) on first launch of this build. Room then re-runs a clean INITIAL
    // bootstrap from FastAPI/PostgreSQL (META_CACHE_COMPLETE is gone -> refreshAll()
    // routes to bootstrapAndReset()). This is a CACHE reset only — it never
    // touches the authoritative PostgreSQL data.
    version = 9,
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
