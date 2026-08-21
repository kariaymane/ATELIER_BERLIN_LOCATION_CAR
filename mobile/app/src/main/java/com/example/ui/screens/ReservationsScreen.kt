package com.example.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.example.data.model.ReservationStatus
import com.example.ui.components.*
import com.example.ui.theme.*
import com.example.ui.viewmodel.FleetViewModel
import com.example.ui.viewmodel.Screen

@Composable
fun ReservationsScreen(
    viewModel: FleetViewModel,
    modifier: Modifier = Modifier
) {
    val reservations by viewModel.reservations.collectAsState()
    val statusFilter by viewModel.reservationStatusFilter.collectAsState()
    val userSession by viewModel.userSession.collectAsState()

    val filterScrollState = rememberScrollState()

    val filterOptions = listOf("Tous", "En cours", "Réservée", "Terminée", "Annulée")

    val filteredReservations = remember(reservations, statusFilter) {
        reservations.filter { r ->
            when (statusFilter) {
                "Tous" -> true
                "En cours" -> r.status == ReservationStatus.EN_COURS
                "Réservée" -> r.status == ReservationStatus.RESERVEE
                "Terminée" -> r.status == ReservationStatus.TERMINEE
                "Annulée" -> r.status == ReservationStatus.ANNULEE
                else -> true
            }
        }
    }

    Box(
        modifier = modifier
            .fillMaxSize()
            .background(ExecutiveBackground)
            .statusBarsPadding()
    ) {
        Column(modifier = Modifier.fillMaxSize()) {
            ExecutiveHeader(
                title = "Réservations",
                subtitle = "${filteredReservations.size} réservation(s)",
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

            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .horizontalScroll(filterScrollState)
                    .padding(horizontal = 16.dp, vertical = 6.dp),
                horizontalArrangement = Arrangement.spacedBy(8.dp)
            ) {
                filterOptions.forEach { option ->
                    FilterChipItem(
                        text = option,
                        isSelected = statusFilter == option,
                        onClick = { viewModel.reservationStatusFilter.value = option }
                    )
                }
            }

            Spacer(modifier = Modifier.height(8.dp))

            if (filteredReservations.isEmpty()) {
                EmptyStateView(
                    title = "Aucune réservation",
                    description = "Aucune réservation trouvée dans la base de données."
                )
            } else {
                LazyColumn(
                    modifier = Modifier
                        .fillMaxSize()
                        .padding(horizontal = 16.dp),
                    verticalArrangement = Arrangement.spacedBy(12.dp),
                    contentPadding = PaddingValues(bottom = 80.dp)
                ) {
                    items(filteredReservations, key = { it.id }) { reservation ->
                        ReservationCard(
                            reservation = reservation,
                            onClick = { viewModel.navigateTo(Screen.ReservationDetail(reservation.id)) }
                        )
                    }
                }
            }
        }
    }
}
