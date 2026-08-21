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
import com.example.data.model.MaintenanceStep
import com.example.ui.components.*
import com.example.ui.theme.*
import com.example.ui.viewmodel.FleetViewModel
import com.example.ui.viewmodel.Screen

@Composable
fun MaintenanceScreen(
    viewModel: FleetViewModel,
    modifier: Modifier = Modifier
) {
    val maintenances by viewModel.maintenances.collectAsState()
    val statusFilter by viewModel.maintenanceStatusFilter.collectAsState()
    val userSession by viewModel.userSession.collectAsState()

    val filterScrollState = rememberScrollState()

    val filterOptions = listOf("Tous", "En attente", "Diagnostic", "Réparation", "Contrôle", "Terminé")

    val filteredTickets = remember(maintenances, statusFilter) {
        maintenances.filter { ticket ->
            when (statusFilter) {
                "Tous" -> true
                "En attente" -> ticket.step == MaintenanceStep.EN_ATTENTE
                "Diagnostic" -> ticket.step == MaintenanceStep.DIAGNOSTIC
                "Réparation" -> ticket.step == MaintenanceStep.REPARATION
                "Contrôle" -> ticket.step == MaintenanceStep.CONTROLE
                "Terminé" -> ticket.step == MaintenanceStep.TERMINEE
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
                title = "Maintenance",
                subtitle = "${filteredTickets.size} ticket(s) en atelier",
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
                        onClick = { viewModel.maintenanceStatusFilter.value = option }
                    )
                }
            }

            Spacer(modifier = Modifier.height(8.dp))

            if (filteredTickets.isEmpty()) {
                EmptyStateView(
                    title = "Aucune maintenance",
                    description = "Tous les véhicules sont opérationnels."
                )
            } else {
                LazyColumn(
                    modifier = Modifier
                        .fillMaxSize()
                        .padding(horizontal = 16.dp),
                    verticalArrangement = Arrangement.spacedBy(12.dp),
                    contentPadding = PaddingValues(bottom = 80.dp)
                ) {
                    items(filteredTickets, key = { it.id }) { ticket ->
                        MaintenanceCard(
                            ticket = ticket,
                            onClick = { viewModel.navigateTo(Screen.MaintenanceDetail(ticket.id)) }
                        )
                    }
                }
            }
        }
    }
}
