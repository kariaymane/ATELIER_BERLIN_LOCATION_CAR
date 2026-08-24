package com.example.data.api

import retrofit2.Response
import retrofit2.http.*

interface ApiService {

    @GET("/health")
    suspend fun getHealth(): Response<SyncHealthResponseDto>

    @GET("sync/bootstrap")
    suspend fun getBootstrap(): Response<SyncBootstrapResponseDto>

    @POST("auth/login")
    suspend fun login(
        @Body body: LoginRequestDto
    ): Response<LoginResponseDto>

    @POST("auth/refresh")
    suspend fun refreshToken(
        @Body body: RefreshRequestDto
    ): Response<RefreshResponseDto>

    @GET("dashboard/stats")
    suspend fun getDashboardStats(): Response<DashboardStatsDto>

    @GET("vehicles/")
    suspend fun getVehicles(
        @Query("page") page: Int = 1,
        @Query("page_size") pageSize: Int = 500,
        @Query("status") status: String? = null,
        @Query("search") search: String? = null
    ): Response<VehicleListResponseDto>

    @GET("vehicles/{id}")
    suspend fun getVehicle(
        @Path("id") id: String
    ): Response<VehicleDto>

    @PATCH("vehicles/{id}/status")
    suspend fun updateVehicleStatus(
        @Path("id") id: String,
        @Body body: VehicleStatusUpdateDto
    ): Response<VehicleDto>

    @GET("rentals/")
    suspend fun getRentals(
        @Query("page") page: Int = 1,
        @Query("page_size") pageSize: Int = 500,
        @Query("status") status: String? = null
    ): Response<RentalListResponseDto>

    @GET("rentals/{id}")
    suspend fun getRental(
        @Path("id") id: String
    ): Response<RentalDto>

    @POST("rentals/")
    suspend fun createRental(
        @Body body: RentalCreateDto
    ): Response<RentalDto>

    @POST("rentals/{id}/activate")
    suspend fun activateRental(
        @Path("id") id: String
    ): Response<RentalDto>

    @POST("rentals/{id}/complete")
    suspend fun completeRental(
        @Path("id") id: String
    ): Response<RentalDto>

    @POST("rentals/{id}/cancel")
    suspend fun cancelRental(
        @Path("id") id: String
    ): Response<RentalDto>

    @GET("maintenance/")
    suspend fun getMaintenances(
        @Query("page") page: Int = 1,
        @Query("size") size: Int = 100,
        @Query("status") status: String? = null
    ): Response<MaintenanceListResponseDto>

    @GET("maintenance/{id}")
    suspend fun getMaintenance(
        @Path("id") id: String
    ): Response<MaintenanceDto>

    @POST("maintenance/")
    suspend fun createMaintenance(
        @Body body: MaintenanceCreateDto
    ): Response<MaintenanceDto>

    @POST("maintenance/{id}/advance")
    suspend fun advanceMaintenance(
        @Path("id") id: String
    ): Response<MaintenanceDto>

    @POST("maintenance/{id}/complete")
    suspend fun completeMaintenance(
        @Path("id") id: String
    ): Response<MaintenanceDto>

    @DELETE("maintenance/{id}")
    suspend fun deleteMaintenance(
        @Path("id") id: String
    ): Response<Unit>

    @GET("notifications/")
    suspend fun getNotifications(
        @Query("page") page: Int = 1,
        @Query("page_size") pageSize: Int = 50,
        @Query("unread_only") unreadOnly: Boolean = false
    ): Response<NotificationListResponseDto>

    @PATCH("notifications/{id}/read")
    suspend fun markNotificationRead(
        @Path("id") id: String
    ): Response<Unit>

    @POST("notifications/mark-all-read")
    suspend fun markAllNotificationsRead(): Response<Unit>

    @GET("clients/")
    suspend fun getClients(
        @Query("page") page: Int = 1,
        @Query("page_size") pageSize: Int = 100,
        @Query("search") search: String? = null
    ): Response<ClientListResponseDto>

    @GET("clients/{id}")
    suspend fun getClient(
        @Path("id") id: String
    ): Response<ClientDto>

    @GET("clients/{id}/rentals")
    suspend fun getClientRentalsReport(
        @Path("id") id: String
    ): Response<ClientRentalsReportDto>
}
