package com.example.ui.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import com.example.data.model.*
import com.example.data.repository.AuthRepository
import com.example.data.repository.FleetRepository
import com.example.ui.components.BottomNavTab
import kotlinx.coroutines.flow.*
import kotlinx.coroutines.launch

import com.example.data.sync.RealtimeSyncManager

sealed class Screen {
    data object Splash : Screen()
    data object Dashboard : Screen()
    data object Vehicles : Screen()
    data class VehicleDetail(val vehicleId: String) : Screen()
    data object Reservations : Screen()
    data class ReservationDetail(val reservationId: String) : Screen()
    data object Maintenance : Screen()
    data class MaintenanceDetail(val maintenanceId: String) : Screen()
    data object Profile : Screen()
    data object Auth : Screen()
}

class FleetViewModel(
    private val authRepository: AuthRepository,
    private val fleetRepository: FleetRepository,
    private val realtimeSyncManager: RealtimeSyncManager? = null,
    private val themePreferences: com.example.data.local.ThemePreferences? = null
) : ViewModel() {

    val userSession: StateFlow<UserSession?> = authRepository.currentUserSession

    val vehicles: StateFlow<List<Vehicle>> = fleetRepository.vehiclesFlow
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), emptyList())

    val reservations: StateFlow<List<Reservation>> = fleetRepository.reservationsFlow
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), emptyList())

    val maintenances: StateFlow<List<MaintenanceTicket>> = fleetRepository.maintenanceFlow
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), emptyList())

    val metrics: StateFlow<PerformanceMetrics?> = fleetRepository.performanceMetricsFlow
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), null)

    val notifications: StateFlow<List<NotificationItem>> = fleetRepository.notificationsFlow
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), emptyList())

    val syncStatus: StateFlow<SyncStatus> = fleetRepository.syncStatusFlow
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), SyncStatus())

    val unreadNotificationCount: StateFlow<Int> = notifications
        .map { list -> list.count { !it.isRead } }
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), 0)

    private val _currentTab = MutableStateFlow(BottomNavTab.DASHBOARD)
    val currentTab: StateFlow<BottomNavTab> = _currentTab.asStateFlow()

    private val _navigationStack = MutableStateFlow<List<Screen>>(listOf(Screen.Splash))
    val navigationStack: StateFlow<List<Screen>> = _navigationStack.asStateFlow()

    private val _currentTheme = MutableStateFlow(themePreferences?.theme ?: com.example.data.local.AppTheme.SYSTEM)
    val currentTheme: StateFlow<com.example.data.local.AppTheme> = _currentTheme.asStateFlow()

    fun setTheme(theme: com.example.data.local.AppTheme) {
        themePreferences?.theme = theme
        _currentTheme.value = theme
    }

    val currentScreen: StateFlow<Screen> = _navigationStack.map { it.lastOrNull() ?: Screen.Splash }
        .stateIn(viewModelScope, SharingStarted.Eagerly, Screen.Splash)

    val vehicleSearchQuery = MutableStateFlow("")
    val vehicleCategoryFilter = MutableStateFlow(VehicleCategory.ALL)
    val vehicleStatusFilter = MutableStateFlow("Tous")

    val reservationSearchQuery = MutableStateFlow("")
    val reservationStatusFilter = MutableStateFlow("Tous")

    val maintenanceSearchQuery = MutableStateFlow("")
    val maintenanceStatusFilter = MutableStateFlow("Tous")

    private val _isLoading = MutableStateFlow(false)
    val isLoading: StateFlow<Boolean> = _isLoading.asStateFlow()

    private val _isRefreshing = MutableStateFlow(false)
    val isRefreshing: StateFlow<Boolean> = _isRefreshing.asStateFlow()

    private val _errorMessage = MutableStateFlow<String?>(null)
    val errorMessage: StateFlow<String?> = _errorMessage.asStateFlow()

    private val _successMessage = MutableStateFlow<String?>(null)
    val successMessage: StateFlow<String?> = _successMessage.asStateFlow()

    init {
        viewModelScope.launch {
            userSession.collect { session ->
                if (session != null) {
                    _navigationStack.value = listOf(Screen.Dashboard)
                    _currentTab.value = BottomNavTab.DASHBOARD
                    refreshAll()
                    realtimeSyncManager?.start()
                } else {
                    realtimeSyncManager?.stop()
                    _navigationStack.value = listOf(Screen.Auth)
                }
            }
        }
    }

    override fun onCleared() {
        super.onCleared()
        realtimeSyncManager?.stop()
    }

    fun navigateTo(screen: Screen) {
        _navigationStack.value = _navigationStack.value + screen
        updateTabForScreen(screen)
    }

    fun navigateBack() {
        val current = _navigationStack.value
        if (current.size > 1) {
            val newStack = current.dropLast(1)
            _navigationStack.value = newStack
            updateTabForScreen(newStack.last())
        }
    }

    fun selectTab(tab: BottomNavTab) {
        _currentTab.value = tab
        val targetScreen = when (tab) {
            BottomNavTab.DASHBOARD -> Screen.Dashboard
            BottomNavTab.VEHICLES -> Screen.Vehicles
            BottomNavTab.RESERVATIONS -> Screen.Reservations
            BottomNavTab.MAINTENANCE -> Screen.Maintenance
            BottomNavTab.PROFILE -> Screen.Profile
        }
        _navigationStack.value = listOf(targetScreen)
    }

    private fun updateTabForScreen(screen: Screen) {
        when (screen) {
            is Screen.Dashboard -> _currentTab.value = BottomNavTab.DASHBOARD
            is Screen.Vehicles, is Screen.VehicleDetail -> _currentTab.value = BottomNavTab.VEHICLES
            is Screen.Reservations, is Screen.ReservationDetail -> _currentTab.value = BottomNavTab.RESERVATIONS
            is Screen.Maintenance, is Screen.MaintenanceDetail -> _currentTab.value = BottomNavTab.MAINTENANCE
            is Screen.Profile -> _currentTab.value = BottomNavTab.PROFILE
            is Screen.Auth -> {}
            is Screen.Splash -> {}
        }
    }

    fun refreshAll() {
        viewModelScope.launch {
            _isRefreshing.value = true
            _errorMessage.value = null
            val result = fleetRepository.refreshAll()
            if (result.isFailure) {
                _errorMessage.value = result.exceptionOrNull()?.message ?: "Erreur de synchronisation avec le serveur API."
            }
            _isRefreshing.value = false
        }
    }

    fun refreshVehicles() {
        viewModelScope.launch {
            _isLoading.value = true
            fleetRepository.refreshVehicles()
            _isLoading.value = false
        }
    }

    fun refreshRentals() {
        viewModelScope.launch {
            _isLoading.value = true
            fleetRepository.refreshRentals()
            _isLoading.value = false
        }
    }

    fun refreshMaintenances() {
        viewModelScope.launch {
            _isLoading.value = true
            fleetRepository.refreshMaintenances()
            _isLoading.value = false
        }
    }

    fun markNotificationRead(id: String) {
        viewModelScope.launch {
            fleetRepository.markNotificationRead(id)
        }
    }

    fun markAllNotificationsRead() {
        viewModelScope.launch {
            fleetRepository.markAllNotificationsRead()
        }
    }

    fun login(email: String, pass: String, onResult: (Boolean) -> Unit) {
        viewModelScope.launch {
            _isLoading.value = true
            _errorMessage.value = null
            val result = authRepository.login(email, pass)
            _isLoading.value = false
            if (result.isSuccess) {
                _navigationStack.value = listOf(Screen.Dashboard)
                _currentTab.value = BottomNavTab.DASHBOARD
                refreshAll()
                onResult(true)
            } else {
                _errorMessage.value = result.exceptionOrNull()?.message ?: "Identifiants invalides."
                onResult(false)
            }
        }
    }

    fun logout() {
        authRepository.logout()
        _navigationStack.value = listOf(Screen.Auth)
    }

    fun updateBaseUrl(url: String) {
        authRepository.updateBaseUrl(url)
        refreshAll()
    }

    fun getBaseUrl(): String = authRepository.getBaseUrl()

    fun resetAndSync(onResult: ((Boolean) -> Unit)? = null) {
        viewModelScope.launch {
            _isLoading.value = true
            _errorMessage.value = null
            _successMessage.value = null
            val result = fleetRepository.bootstrapAndReset()
            _isLoading.value = false
            if (result.isSuccess) {
                _successMessage.value = "Réinitialisation et synchronisation terminées avec succès."
                onResult?.invoke(true)
            } else {
                _errorMessage.value = result.exceptionOrNull()?.message ?: "Échec de la réinitialisation."
                onResult?.invoke(false)
            }
        }
    }

    fun testConnection(onResult: (Boolean, String) -> Unit) {
        viewModelScope.launch {
            _isLoading.value = true
            val result = fleetRepository.testConnection()
            _isLoading.value = false
            if (result.isSuccess) {
                onResult(true, result.getOrNull() ?: "Connecté")
            } else {
                onResult(false, result.exceptionOrNull()?.message ?: "Inaccessible")
            }
        }
    }

    fun clearMessages() {
        _errorMessage.value = null
        _successMessage.value = null
    }
}

class FleetViewModelFactory(
    private val authRepository: AuthRepository,
    private val fleetRepository: FleetRepository,
    private val realtimeSyncManager: RealtimeSyncManager,
    private val themePreferences: com.example.data.local.ThemePreferences
) : ViewModelProvider.Factory {
    override fun <T : ViewModel> create(modelClass: Class<T>): T {
        if (modelClass.isAssignableFrom(FleetViewModel::class.java)) {
            @Suppress("UNCHECKED_CAST")
            return FleetViewModel(authRepository, fleetRepository, realtimeSyncManager, themePreferences) as T
        }
        throw IllegalArgumentException("Unknown ViewModel class")
    }
}
