package com.example.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material.icons.outlined.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.layout.ContentScale
import androidx.compose.foundation.Image
import androidx.compose.ui.res.painterResource
import com.example.R
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import com.example.ui.components.*
import com.example.ui.theme.*
import com.example.ui.viewmodel.FleetViewModel
import com.example.ui.viewmodel.Screen

@Composable
fun DashboardScreen(
    viewModel: FleetViewModel,
    modifier: Modifier = Modifier
) {
    val metrics by viewModel.metrics.collectAsState()
    val vehicles by viewModel.vehicles.collectAsState()
    val isRefreshing by viewModel.isRefreshing.collectAsState()
    val userSession by viewModel.userSession.collectAsState()
    val syncStatus by viewModel.syncStatus.collectAsState()

    val scrollState = rememberScrollState()
    val horizontalScrollState = rememberScrollState()

    val unreadNotifs by viewModel.unreadNotificationCount.collectAsState()
    val notifications by viewModel.notifications.collectAsState()
    var showNotifsSheet by remember { mutableStateOf(false) }

    if (showNotifsSheet) {
        NotificationsModalBottomSheet(
            notifications = notifications,
            onDismiss = { showNotifsSheet = false },
            onMarkRead = { viewModel.markNotificationRead(it) },
            onMarkAllRead = { viewModel.markAllNotificationsRead() }
        )
    }

    Column(
        modifier = modifier
            .fillMaxSize()
            .background(ExecutiveBackground)
            .statusBarsPadding()
    ) {
        // Top Header
        ExecutiveHeader(
            title = "ATELIER BERLIN LOCATION CAR",
            subtitle = "Tableau de bord",
            userInitials = userSession?.initials ?: "SE",
            unreadNotifs = unreadNotifs,
            onNotificationClick = { showNotifsSheet = true },
            onProfileClick = { viewModel.selectTab(BottomNavTab.PROFILE) }
        )

        OfflineBanner(
            syncStatus = syncStatus,
            hasCachedData = vehicles.isNotEmpty() || metrics != null,
            onRetry = { viewModel.retrySync() },
        )

        Column(
            modifier = Modifier
                .fillMaxSize()
                .verticalScroll(scrollState)
                .padding(bottom = 24.dp)
        ) {
            // Main Top Title matching screenshot 1
            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 20.dp, vertical = 12.dp),
                horizontalAlignment = Alignment.CenterHorizontally
            ) {
                Image(
                    painter = painterResource(id = R.drawable.logo_transparent_officiel),
                    contentDescription = "ATELIER BERLIN LOCATION CAR Logo",
                    contentScale = ContentScale.Fit,
                    modifier = Modifier
                        .width(190.dp)
                        .wrapContentHeight()
                )
                Spacer(modifier = Modifier.height(4.dp))
                Text(
                    text = "Gestion de Flotte Automobile & Opérations",
                    fontSize = 13.sp,
                    color = ExecutiveTextSecondary,
                    textAlign = TextAlign.Center
                )
            }

            Spacer(modifier = Modifier.height(8.dp))


            Spacer(modifier = Modifier.height(14.dp))

            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .horizontalScroll(horizontalScrollState)
                    .padding(horizontal = 16.dp),
                horizontalArrangement = Arrangement.spacedBy(12.dp)
            ) {
                OperationalStatCard(
                    label = "Aujourd'hui",
                    value = "${metrics?.todayBookings ?: 0}",
                    subtitle = "réservations",
                    modifier = Modifier.width(130.dp)
                )
                OperationalStatCard(
                    label = "Cette semaine",
                    value = "${metrics?.weekBookings ?: 0}",
                    subtitle = "réservations",
                    modifier = Modifier.width(140.dp)
                )
                OperationalStatCard(
                    label = "Ce mois",
                    value = "${metrics?.monthBookings ?: 0}",
                    subtitle = "réservations",
                    modifier = Modifier.width(145.dp)
                )
            }

            Spacer(modifier = Modifier.height(14.dp))

            // Revenue stats row
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .horizontalScroll(androidx.compose.foundation.rememberScrollState())
                    .padding(horizontal = 16.dp),
                horizontalArrangement = Arrangement.spacedBy(12.dp)
            ) {
                OperationalStatCard(
                    label = "Aujourd'hui",
                    value = "${String.format("%.0f", metrics?.todayRevenue ?: 0.0)} DH",
                    subtitle = "chiffre d'affaires",
                    modifier = Modifier.width(130.dp)
                )
                OperationalStatCard(
                    label = "Cette semaine",
                    value = "${String.format("%.0f", metrics?.weekRevenue ?: 0.0)} DH",
                    subtitle = "chiffre d'affaires",
                    modifier = Modifier.width(140.dp)
                )
                OperationalStatCard(
                    label = "Ce mois",
                    value = "${String.format("%.0f", metrics?.monthRevenue ?: 0.0)} DH",
                    subtitle = "chiffre d'affaires",
                    modifier = Modifier.width(145.dp)
                )
                OperationalStatCard(
                    label = "Cette année",
                    value = "${String.format("%.0f", metrics?.yearRevenue ?: 0.0)} DH",
                    subtitle = "chiffre d'affaires",
                    modifier = Modifier.width(150.dp)
                )
            }

            Spacer(modifier = Modifier.height(28.dp))

            // Section "État de la flotte"
            Text(
                text = "État de la flotte",
                fontSize = 20.sp,
                fontWeight = FontWeight.SemiBold,
                fontFamily = FontFamily.Serif,
                color = ExecutiveTextPrimary,
                modifier = Modifier.padding(horizontal = 20.dp)
            )

            Spacer(modifier = Modifier.height(14.dp))

            // 2x2 Grid of Fleet Count Cards matching screenshot 1
            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 16.dp),
                verticalArrangement = Arrangement.spacedBy(14.dp)
            ) {
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.spacedBy(14.dp)
                ) {
                    FleetCountCard(
                        title = "Prêts à louer",
                        count = metrics?.readyVehicles ?: 0,
                        icon = Icons.Default.DirectionsCar,
                        iconColor = StatusGreenDot,
                        modifier = Modifier.weight(1f)
                    )
                    FleetCountCard(
                        title = "En location",
                        count = metrics?.rentedVehicles ?: 0,
                        icon = Icons.Default.AltRoute,
                        iconColor = StatusOrangeDot,
                        modifier = Modifier.weight(1f)
                    )
                }
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.spacedBy(14.dp)
                ) {
                    FleetCountCard(
                        title = "Réservés",
                        count = metrics?.reservedVehicles ?: 0,
                        icon = Icons.Default.CalendarMonth,
                        iconColor = StatusGoldDot,
                        modifier = Modifier.weight(1f)
                    )
                    FleetCountCard(
                        title = "En maintenance",
                        count = metrics?.maintenanceVehicles ?: 0,
                        icon = Icons.Default.Build,
                        iconColor = StatusRedDot,
                        modifier = Modifier.weight(1f)
                    )
                }
            }

            Spacer(modifier = Modifier.height(28.dp))

            // Quick access to vehicles section
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 20.dp),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically
            ) {
                Text(
                    text = "Véhicules récents",
                    fontSize = 18.sp,
                    fontWeight = FontWeight.Bold,
                    color = ExecutiveTextPrimary
                )
                TextButton(onClick = { viewModel.selectTab(BottomNavTab.VEHICLES) }) {
                    Text(
                        text = "Voir tout",
                        color = ExecutivePrimaryGreen,
                        fontWeight = FontWeight.SemiBold,
                        fontSize = 13.sp
                    )
                }
            }

            Spacer(modifier = Modifier.height(8.dp))

            if (vehicles.isEmpty()) {
                val dbDown = syncStatus.isServerDatabaseDown
                val isError = syncStatus.isShowingStaleData
                EmptyStateView(
                    title = when {
                        dbDown -> "Base de données du serveur indisponible"
                        isError -> "Connexion au serveur impossible"
                        else -> "Aucun véhicule disponible"
                    },
                    description = when {
                        dbDown -> "Le serveur est accessible mais sa base de données ne répond pas. Réessayez dans un instant."
                        isError -> "Veuillez vérifier votre connexion au serveur."
                        else -> "La liste des véhicules est vide."
                    },
                    onAction = { viewModel.retrySync() },
                    actionLabel = "Actualiser les données"
                )
            } else {
                Column(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(horizontal = 16.dp),
                    verticalArrangement = Arrangement.spacedBy(10.dp)
                ) {
                    vehicles.take(3).forEach { vehicle ->
                        VehicleCard(
                            vehicle = vehicle,
                            onClick = { viewModel.navigateTo(Screen.VehicleDetail(vehicle.id)) }
                        )
                    }
                }
            }
        }
    }
}
