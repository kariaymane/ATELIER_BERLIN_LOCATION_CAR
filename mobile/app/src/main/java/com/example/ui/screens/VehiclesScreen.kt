package com.example.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.example.data.model.VehicleCategory
import com.example.data.model.VehicleStatus
import com.example.ui.components.*
import com.example.ui.theme.*
import com.example.ui.viewmodel.FleetViewModel
import com.example.ui.viewmodel.Screen

@Composable
fun VehiclesScreen(
    viewModel: FleetViewModel,
    modifier: Modifier = Modifier
) {
    val vehicles by viewModel.vehicles.collectAsState()
    val isRefreshing by viewModel.isRefreshing.collectAsState()
    val searchQuery by viewModel.vehicleSearchQuery.collectAsState()
    val categoryFilter by viewModel.vehicleCategoryFilter.collectAsState()
    val userSession by viewModel.userSession.collectAsState()
    val syncStatus by viewModel.syncStatus.collectAsState()

    val filterScrollState = rememberScrollState()

    val filteredVehicles = remember(vehicles, searchQuery, categoryFilter) {
        vehicles.filter { v ->
            val matchesQuery = searchQuery.isBlank() ||
                    v.brand.contains(searchQuery, ignoreCase = true) ||
                    v.modelName.contains(searchQuery, ignoreCase = true) ||
                    v.plate.contains(searchQuery, ignoreCase = true)

            val matchesFilter = when (categoryFilter) {
                VehicleCategory.ALL -> true
                VehicleCategory.DISPONIBLE -> v.status == VehicleStatus.DISPONIBLE
                VehicleCategory.EN_LOCATION -> v.status == VehicleStatus.EN_LOCATION
                VehicleCategory.MAINTENANCE -> v.status == VehicleStatus.MAINTENANCE
            }

            matchesQuery && matchesFilter
        }
    }

    Column(
        modifier = modifier
            .fillMaxSize()
            .background(ExecutiveBackground)
            .statusBarsPadding()
    ) {
        // Top Header matching screenshot 6
        ExecutiveHeader(
            title = "Véhicules",
            subtitle = "${filteredVehicles.size} véhicule(s) affiché(s)",
            userInitials = userSession?.initials ?: "SE",
            actions = {
                IconButton(onClick = { viewModel.refreshAll() }) {
                    Icon(
                        imageVector = Icons.Default.Refresh,
                        contentDescription = "Actualiser",
                        tint = ExecutiveTextPrimary
                    )
                }
            }
        )

        OfflineBanner(
            syncStatus = syncStatus,
            hasCachedData = vehicles.isNotEmpty(),
            onRetry = { viewModel.retrySync() },
        )

        // Search Bar matching screenshot 6
        Box(modifier = Modifier.padding(horizontal = 16.dp, vertical = 6.dp)) {
            ExecutiveSearchBar(
                query = searchQuery,
                onQueryChange = { viewModel.vehicleSearchQuery.value = it },
                placeholder = "Rechercher par marque ou immatriculation"
            )
        }

        Spacer(modifier = Modifier.height(6.dp))

        // Filter Chips Row
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .horizontalScroll(filterScrollState)
                .padding(horizontal = 16.dp, vertical = 4.dp),
            horizontalArrangement = Arrangement.spacedBy(8.dp)
        ) {
            VehicleCategory.entries.forEach { cat ->
                FilterChipItem(
                    text = cat.label,
                    isSelected = categoryFilter == cat,
                    onClick = { viewModel.vehicleCategoryFilter.value = cat }
                )
            }
        }

        Spacer(modifier = Modifier.height(10.dp))

        // Vehicle List
        if (filteredVehicles.isEmpty()) {
            val hasCache = vehicles.isNotEmpty()
            val dbDown = syncStatus.isServerDatabaseDown && !hasCache
            val isError = syncStatus.isShowingStaleData && !hasCache

            EmptyStateView(
                title = when {
                    dbDown -> "Base de données du serveur indisponible"
                    isError -> "Connexion au serveur impossible"
                    searchQuery.isNotBlank() -> "Aucun résultat"
                    else -> "Aucun véhicule disponible"
                },
                description = when {
                    dbDown -> "Le serveur est accessible mais sa base de données ne répond pas. Réessayez dans un instant."
                    isError -> "Veuillez vérifier votre connexion au serveur."
                    searchQuery.isNotBlank() -> "Aucun véhicule ne correspond à \"$searchQuery\"."
                    else -> "La liste des véhicules est vide."
                },
                onAction = { viewModel.retrySync() },
                actionLabel = "Actualiser"
            )
        } else {
            LazyColumn(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(horizontal = 16.dp),
                verticalArrangement = Arrangement.spacedBy(12.dp),
                contentPadding = PaddingValues(bottom = 24.dp)
            ) {
                items(filteredVehicles, key = { it.id }) { vehicle ->
                    VehicleCard(
                        vehicle = vehicle,
                        onClick = { viewModel.navigateTo(Screen.VehicleDetail(vehicle.id)) }
                    )
                }
            }
        }
    }
}
