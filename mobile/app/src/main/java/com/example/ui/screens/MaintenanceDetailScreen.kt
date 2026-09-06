package com.example.ui.screens

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.example.ui.theme.*
import com.example.ui.viewmodel.FleetViewModel

/**
 * Maintenance detail — the new model, identical in meaning to the Desktop.
 *
 * A maintenance is a PERIOD, not a sequence of steps. It is EN COURS while
 * `now < end` and TERMINÉE from `now >= end` (see
 * `MaintenanceTicket.isCompleted`). There is no Diagnostic / Réparation /
 * Test / Finalisée stage and no action to advance one: nothing here mutates
 * the ticket's progress, the clock does.
 *
 * The screen stays simple: vehicle, status, start, end, reason, details, then
 * the useful facts the system already holds (garage, technicien, kilométrage,
 * facturation).
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun MaintenanceDetailScreen(
    maintenanceId: String,
    viewModel: FleetViewModel,
    onBack: () -> Unit
) {
    val maintenances by viewModel.maintenances.collectAsState()
    val ticket = maintenances.find { it.id == maintenanceId }

    if (ticket == null) {
        Column(
            modifier = Modifier.fillMaxSize(),
            verticalArrangement = Arrangement.Center,
            horizontalAlignment = Alignment.CenterHorizontally
        ) {
            Text("Maintenance introuvable")
            Button(onClick = onBack) {
                Text("Retour")
            }
        }
        return
    }

    val scrollState = rememberScrollState()

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("Maintenance") },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Retour")
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(
                    containerColor = ExecutiveSurface,
                    titleContentColor = ExecutiveTextPrimary
                )
            )
        },
        containerColor = ExecutiveBackground
    ) { padding ->
        Column(
            modifier = Modifier
                .padding(padding)
                .fillMaxSize()
                .verticalScroll(scrollState)
                .padding(16.dp)
        ) {
            // ── Vehicle + status ──────────────────────────────────────
            MaintenanceSection {
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween,
                    verticalAlignment = Alignment.Top
                ) {
                    Column(modifier = Modifier.weight(1f)) {
                        Text(
                            text = "Véhicule",
                            fontSize = 12.sp,
                            color = ExecutiveTextTertiary,
                            fontWeight = FontWeight.Medium
                        )
                        Text(
                            text = ticket.vehicleName,
                            fontSize = 20.sp,
                            fontWeight = FontWeight.Bold,
                            color = ExecutiveTextPrimary
                        )
                        if (ticket.vehiclePlate.isNotBlank()) {
                            Text(
                                text = ticket.vehiclePlate,
                                fontSize = 14.sp,
                                fontWeight = FontWeight.SemiBold,
                                color = ExecutivePrimaryGreen
                            )
                        }
                    }
                    Spacer(modifier = Modifier.width(12.dp))
                    val isCompleted = ticket.isCompleted
                    val isCancelled = ticket.isCancelled
                    com.example.ui.components.StatusBadge(
                        text = ticket.effectiveStatusDisplay,
                        backgroundColor = when {
                            isCancelled -> StatusRedBg
                            isCompleted -> StatusGreenBg
                            else -> StatusGoldBg
                        },
                        textColor = when {
                            isCancelled -> StatusRedText
                            isCompleted -> StatusGreenText
                            else -> StatusGoldText
                        },
                        dotColor = when {
                            isCancelled -> StatusRedDot
                            isCompleted -> StatusGreenDot
                            else -> StatusGoldDot
                        }
                    )
                }
            }

            Spacer(modifier = Modifier.height(16.dp))

            // ── Period + reason + details ─────────────────────────────
            MaintenanceSection {
                SectionTitle("Intervention")
                Spacer(modifier = Modifier.height(12.dp))

                DetailRow("Statut", ticket.effectiveStatusDisplay)
                DetailRow("Début", ticket.scheduledDate.ifBlank { "—" })
                DetailRow("Fin", ticket.scheduledEndDate.ifBlank { "—" })
                DetailRow("Motif", ticket.motif)

                if (ticket.description.isNotBlank()) {
                    Spacer(modifier = Modifier.height(10.dp))
                    Text(
                        text = "Détails",
                        fontSize = 13.sp,
                        fontWeight = FontWeight.SemiBold,
                        color = ExecutiveTextSecondary
                    )
                    Spacer(modifier = Modifier.height(4.dp))
                    Text(
                        text = ticket.description,
                        fontSize = 14.sp,
                        color = ExecutiveTextPrimary
                    )
                }
            }

            // ── Workshop facts, only when the system holds them ───────
            val hasWorkshopInfo = !ticket.location.isNullOrBlank() ||
                ticket.technician.isNotBlank() ||
                ticket.mileage != null ||
                !ticket.invoice_number.isNullOrBlank()

            if (hasWorkshopInfo) {
                Spacer(modifier = Modifier.height(16.dp))
                MaintenanceSection {
                    SectionTitle("Atelier")
                    Spacer(modifier = Modifier.height(12.dp))
                    if (!ticket.location.isNullOrBlank()) {
                        DetailRow("Garage", ticket.location!!)
                    }
                    if (ticket.technician.isNotBlank()) {
                        DetailRow("Technicien", ticket.technician)
                    }
                    ticket.mileage?.let { DetailRow("Kilométrage", "${it.toLong()} km") }
                    if (!ticket.invoice_number.isNullOrBlank()) {
                        DetailRow("N° Facture", ticket.invoice_number!!)
                    }
                }
            }

            // ── Costs ─────────────────────────────────────────────────
            val total = ticket.actual_cost ?: ticket.estimatedCost.toDouble()
            val hasCosts = total > 0 || ticket.parts.isNotEmpty()

            if (hasCosts) {
                Spacer(modifier = Modifier.height(16.dp))
                MaintenanceSection {
                    SectionTitle("Facturation")
                    Spacer(modifier = Modifier.height(12.dp))

                    if (ticket.parts.isNotEmpty()) {
                        Text(
                            text = "Pièces de rechange",
                            fontWeight = FontWeight.SemiBold,
                            fontSize = 13.sp,
                            color = ExecutiveTextSecondary
                        )
                        ticket.parts.forEach { part ->
                            Row(
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .padding(vertical = 4.dp),
                                horizontalArrangement = Arrangement.SpaceBetween,
                                verticalAlignment = Alignment.Top
                            ) {
                                Text(
                                    text = "- ${part.part_name} (x${part.quantity})",
                                    fontSize = 14.sp,
                                    color = ExecutiveTextPrimary,
                                    modifier = Modifier.weight(1f)
                                )
                                Spacer(modifier = Modifier.width(8.dp))
                                Text(
                                    text = "${part.total_price} DH",
                                    fontSize = 14.sp,
                                    fontWeight = FontWeight.SemiBold,
                                    color = ExecutiveTextPrimary
                                )
                            }
                        }
                        Spacer(modifier = Modifier.height(8.dp))
                    }

                    DetailRow("Coût Pièces", "${ticket.parts_cost} DH")
                    DetailRow("Main d'œuvre", "${ticket.labor_cost} DH")
                    DetailRow("Autres Frais", "${ticket.other_cost} DH")

                    HorizontalDivider(
                        modifier = Modifier.padding(vertical = 10.dp),
                        thickness = 1.dp,
                        color = ExecutiveBorder
                    )

                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.SpaceBetween
                    ) {
                        Text("Total", fontSize = 16.sp, fontWeight = FontWeight.Bold,
                            color = ExecutiveTextPrimary)
                        Text(
                            text = "$total DH",
                            fontSize = 16.sp,
                            fontWeight = FontWeight.Bold,
                            color = ExecutivePrimaryGreen
                        )
                    }
                }
            }

            Spacer(modifier = Modifier.height(24.dp))
        }
    }
}

@Composable
private fun MaintenanceSection(content: @Composable ColumnScope.() -> Unit) {
    Surface(
        modifier = Modifier
            .fillMaxWidth()
            .shadow(elevation = 2.dp, shape = RoundedCornerShape(18.dp)),
        shape = RoundedCornerShape(18.dp),
        color = ExecutiveSurface,
        border = androidx.compose.foundation.BorderStroke(1.dp, ExecutiveBorder)
    ) {
        Column(modifier = Modifier.padding(18.dp), content = content)
    }
}

@Composable
private fun SectionTitle(text: String) {
    Text(
        text = text,
        fontSize = 18.sp,
        fontWeight = FontWeight.Bold,
        color = ExecutiveTextPrimary
    )
}

/**
 * Label on the left, value on the right. The value takes the remaining width
 * and wraps rather than being clipped, so a long garage name or a long reason
 * stays fully readable on a phone.
 */
@Composable
fun DetailRow(label: String, value: String) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = 4.dp),
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.Top
    ) {
        Text(
            text = label,
            fontSize = 14.sp,
            fontWeight = FontWeight.SemiBold,
            color = ExecutiveTextSecondary
        )
        Spacer(modifier = Modifier.width(12.dp))
        Text(
            text = value,
            fontSize = 14.sp,
            fontWeight = FontWeight.Medium,
            color = ExecutiveTextPrimary,
            modifier = Modifier.weight(1f, fill = false),
            textAlign = androidx.compose.ui.text.style.TextAlign.End
        )
    }
}
