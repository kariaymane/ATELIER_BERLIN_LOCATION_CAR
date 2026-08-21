package com.example

import com.example.data.model.MaintenanceStep
import com.example.data.model.PerformanceMetrics
import com.example.data.model.ReservationStatus
import com.example.data.model.Vehicle
import com.example.data.model.VehicleCategory
import com.example.data.model.VehicleStatus
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class FleetDataTest {

    @Test
    fun testVehicleModelProperties() {
        val vehicle = Vehicle(
            id = "v_1",
            brand = "Mercedes-Benz",
            modelName = "S-Class",
            plate = "FR-789-AB",
            year = 2024,
            dailyRate = 250,
            status = VehicleStatus.DISPONIBLE,
            category = "Sedan",
            imageUrl = "https://example.com/sclass.jpg",
            mileage = 15400,
            fuelType = "Hybride Rechargeable",
            transmission = "Automatique 9G-Tronic",
            power = "435 ch",
            description = "Berline de grand luxe."
        )

        assertEquals("Mercedes-Benz S-Class", vehicle.fullName)
        assertEquals(250, vehicle.dailyRate)
        assertEquals(VehicleStatus.DISPONIBLE, vehicle.status)
        assertEquals("Disponible", vehicle.status.label)
    }

    @Test
    fun testCategoryFilteringLogic() {
        val vehicle1 = Vehicle(
            id = "v_1",
            brand = "Mercedes-Benz",
            modelName = "S-Class",
            plate = "FR-789-AB",
            year = 2024,
            dailyRate = 250,
            status = VehicleStatus.DISPONIBLE,
            category = "Sedan",
            imageUrl = "",
            mileage = 1000,
            fuelType = "Essence",
            transmission = "Auto",
            power = "300 ch",
            description = ""
        )

        val vehicle2 = Vehicle(
            id = "v_2",
            brand = "Range Rover",
            modelName = "Autobiography",
            plate = "FR-456-CD",
            year = 2024,
            dailyRate = 320,
            status = VehicleStatus.EN_LOCATION,
            category = "SUV",
            imageUrl = "",
            mileage = 8000,
            fuelType = "Diesel Hybride",
            transmission = "Auto",
            power = "350 ch",
            description = ""
        )

        val list = listOf(vehicle1, vehicle2)

        val disponible = list.filter { it.status == VehicleStatus.DISPONIBLE }
        assertEquals(1, disponible.size)
        assertEquals("Mercedes-Benz S-Class", disponible[0].fullName)

        val suvOnly = list.filter { it.category.equals("SUV", ignoreCase = true) }
        assertEquals(1, suvOnly.size)
        assertEquals("Range Rover Autobiography", suvOnly[0].fullName)
    }

    @Test
    fun testPerformanceMetricsData() {
        val metrics = PerformanceMetrics(
            todayBookings = 35,
            weekBookings = 210,
            monthBookings = 850,
            readyVehicles = 125,
            rentedVehicles = 98,
            reservedVehicles = 30,
            maintenanceVehicles = 12
        )

        assertEquals(35, metrics.todayBookings)
        assertEquals(210, metrics.weekBookings)
        assertEquals(850, metrics.monthBookings)
        assertEquals(125, metrics.readyVehicles)
        assertEquals(98, metrics.rentedVehicles)
        assertEquals(30, metrics.reservedVehicles)
        assertEquals(12, metrics.maintenanceVehicles)
    }

    @Test
    fun testStatusLabels() {
        assertEquals("Disponible", VehicleStatus.DISPONIBLE.label)
        assertEquals("En location", VehicleStatus.EN_LOCATION.label)
        assertEquals("En attente", MaintenanceStep.EN_ATTENTE.label)
        assertEquals("Diagnostic", MaintenanceStep.DIAGNOSTIC.label)
        assertEquals("Réparation", MaintenanceStep.REPARATION.label)
        assertEquals("Contrôle", MaintenanceStep.CONTROLE.label)
        assertEquals("Terminé", MaintenanceStep.TERMINEE.label)
        assertEquals("Réservée", ReservationStatus.RESERVEE.label)
        assertEquals("En cours", ReservationStatus.EN_COURS.label)
        assertEquals("Terminée", ReservationStatus.TERMINEE.label)
    }
}
