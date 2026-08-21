package com.example.data.local

import androidx.room.Embedded
import androidx.room.Relation

data class VehicleWithImages(
    @Embedded val vehicle: VehicleEntity,
    @Relation(
        parentColumn = "id",
        entityColumn = "vehicleId"
    )
    val images: List<VehicleImageEntity>
)
