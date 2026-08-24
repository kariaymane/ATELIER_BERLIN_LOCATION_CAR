package com.example.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.example.ui.theme.ExecutiveGold
import com.example.ui.viewmodel.FleetViewModel

private val ClientSurface = Color(0xFF1E4D38)
private val ClientMuted = Color(0xFF6B7264)

/**
 * Clients — read-only list backed by the canonical backend contract.
 * No local business logic: every value is server-authoritative.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ClientsScreen(viewModel: FleetViewModel) {
    var clients by remember { mutableStateOf<List<com.example.data.api.ClientDto>>(emptyList()) }
    var loading by remember { mutableStateOf(true) }
    var error by remember { mutableStateOf<String?>(null) }
    var search by remember { mutableStateOf("") }

    LaunchedEffect(Unit) { load(viewModel) { c, e -> clients = c; error = e; loading = false } }
    LaunchedEffect(search) {
        kotlinx.coroutines.delay(300)
        load(viewModel, search.ifBlank { null }) { c, e -> clients = c; error = e; loading = false }
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(16.dp)
    ) {
        Text("Clients", fontSize = 22.sp, fontWeight = FontWeight.Bold, color = ClientSurface)
        Spacer(Modifier.height(10.dp))
        OutlinedTextField(
            value = search,
            onValueChange = { search = it },
            modifier = Modifier.fillMaxWidth(),
            singleLine = true,
            placeholder = { Text("Rechercher (nom, téléphone, CIN)...", fontSize = 13.sp) },
            shape = RoundedCornerShape(10.dp)
        )
        Spacer(Modifier.height(12.dp))

        when {
            loading -> Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                CircularProgressIndicator(color = ExecutiveGold)
            }
            error != null -> Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                Text(error!!, color = Color(0xFFB91C1C), fontSize = 14.sp)
            }
            clients.isEmpty() -> Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                Text("Aucun client", color = ClientMuted, fontSize = 14.sp)
            }
            else -> LazyColumn(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                items(clients) { client ->
                    Card(
                        modifier = Modifier
                            .fillMaxWidth()
                            .clickable { viewModel.navigateTo(com.example.ui.viewmodel.Screen.ClientDetail(client.id)) },
                        shape = RoundedCornerShape(12.dp),
                        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface)
                    ) {
                        Column(Modifier.padding(14.dp)) {
                            Text(
                                "${client.firstName} ${client.lastName}".trim().ifBlank { "—" },
                                fontWeight = FontWeight.Bold, fontSize = 15.sp,
                                color = MaterialTheme.colorScheme.onSurface
                            )
                            Spacer(Modifier.height(4.dp))
                            Text(
                                listOfNotNull(
                                    client.phone?.takeIf { it.isNotBlank() },
                                    client.cinNumber?.takeIf { it.isNotBlank() }
                                ).joinToString("  ·  ").ifBlank { "—" },
                                fontSize = 12.sp, color = ClientMuted
                            )
                        }
                    }
                }
            }
        }
    }
}

@Composable
fun ClientDetailScreen(clientId: String, viewModel: FleetViewModel) {
    var report by remember { mutableStateOf<com.example.data.api.ClientRentalsReportDto?>(null) }
    var client by remember { mutableStateOf<com.example.data.api.ClientDto?>(null) }
    var error by remember { mutableStateOf<String?>(null) }

    LaunchedEffect(clientId) {
        viewModel.getClientRentalsReport(clientId)
            .onSuccess { report = it }
            .onFailure { error = it.message ?: "Erreur" }
        viewModel.getClients()
            .onSuccess { list -> client = list.firstOrNull { it.id == clientId } }
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(16.dp)
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            TextButton(onClick = { viewModel.navigateBack() }) { Text("< Retour") }
            Spacer(Modifier.width(6.dp))
            Text(
                "${client?.firstName ?: ""} ${client?.lastName ?: ""}".trim().ifBlank { "Client" },
                fontSize = 19.sp, fontWeight = FontWeight.Bold, color = ClientSurface
            )
        }
        Spacer(Modifier.height(8.dp))

        when {
            error != null && report == null ->
                Text(error!!, color = Color(0xFFB91C1C), fontSize = 13.sp)
            report == null -> Box(Modifier.fillMaxWidth().height(120.dp), contentAlignment = Alignment.Center) {
                CircularProgressIndicator(color = ExecutiveGold)
            }
            else -> {
                val s = report!!.summary
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    KpiCard("Locations", "${s.totalRentals}", Modifier.weight(1f))
                    KpiCard("Jours", "${s.totalDays}", Modifier.weight(1f))
                    KpiCard("Total", String.format("%.2f DH", s.totalAmount), Modifier.weight(1.4f))
                }
                Spacer(Modifier.height(8.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    KpiCard("En cours", "${s.activeRentals}", Modifier.weight(1f))
                    KpiCard("Terminées", "${s.completedRentals}", Modifier.weight(1f))
                    KpiCard("Annulées", "${s.cancelledRentals}", Modifier.weight(1f))
                    KpiCard("Véhicules", "${s.vehiclesRented}", Modifier.weight(1f))
                }
                Spacer(Modifier.height(12.dp))

                Text("Historique des locations", fontWeight = FontWeight.Bold, fontSize = 15.sp, color = ClientSurface)
                Spacer(Modifier.height(6.dp))
                LazyColumn(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    items(report!!.rentals) { r ->
                        Card(shape = RoundedCornerShape(10.dp)) {
                            Column(Modifier.padding(12.dp)) {
                                Text(
                                    "${r.vehicleBrand.orEmpty()} ${r.vehicleModel.orEmpty()}".trim()
                                        .ifBlank { r.vehicleRegistration ?: "—" } +
                                        "  (${r.vehicleRegistration ?: "—"})",
                                    fontWeight = FontWeight.SemiBold, fontSize = 13.sp
                                )
                                Spacer(Modifier.height(3.dp))
                                Text(
                                    "${r.startDatetime?.take(16)?.replace('T', ' ')} → " +
                                        "${r.endDatetime?.take(16)?.replace('T', ' ')}",
                                    fontSize = 11.sp, color = ClientMuted
                                )
                                Spacer(Modifier.height(3.dp))
                                Text(
                                    "${r.numDays} j · ${String.format("%.2f", r.dailyPrice)} DH/j · " +
                                        "Total ${String.format("%.2f", r.totalPrice)} DH · ${r.status}",
                                    fontSize = 12.sp,
                                    color = if (r.status == "CANCELLED") Color(0xFF975A16)
                                            else MaterialTheme.colorScheme.onSurface
                                )
                            }
                        }
                    }
                    item {
                        if (report!!.vehicles.isNotEmpty()) {
                            Text(
                                report!!.vehicles.joinToString("  ·  ") { v ->
                                    "${v.brand} ${v.model} (${v.registration}): " +
                                        "${v.rentals} loc / ${v.days} j / ${String.format("%.2f", v.amount)} DH"
                                },
                                fontSize = 11.sp, color = ClientMuted,
                                modifier = Modifier.padding(top = 6.dp, bottom = 20.dp)
                            )
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun KpiCard(label: String, value: String, modifier: Modifier = Modifier) {
    Surface(color = ClientSurface, shape = RoundedCornerShape(10.dp), modifier = modifier) {
        Column(Modifier.padding(10.dp)) {
            Text(label, fontSize = 10.sp, color = Color(0xFFCDE3D5))
            Text(value, fontSize = 15.sp, fontWeight = FontWeight.Bold, color = Color.White)
        }
    }
}

private suspend fun load(
    viewModel: FleetViewModel,
    search: String? = null,
    setState: (List<com.example.data.api.ClientDto>, String?) -> Unit
) {
    viewModel.getClients(search)
        .onSuccess { setState(it, null) }
        .onFailure { setState(emptyList(), it.message ?: "Erreur de connexion") }
}
