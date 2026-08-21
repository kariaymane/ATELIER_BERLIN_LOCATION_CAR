package com.example.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.example.data.model.MaintenanceStep
import com.example.ui.theme.*
import com.example.ui.viewmodel.FleetViewModel

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
            Text("Billet de maintenance introuvable")
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
                title = { Text("Détails d'Intervention") },
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
            // Card 1: Véhicule & Statut Global
            Surface(
                modifier = Modifier
                    .fillMaxWidth()
                    .shadow(elevation = 2.dp, shape = RoundedCornerShape(18.dp)),
                shape = RoundedCornerShape(18.dp),
                color = ExecutiveSurface,
                border = androidx.compose.foundation.BorderStroke(1.dp, ExecutiveBorder)
            ) {
                Column(modifier = Modifier.padding(18.dp)) {
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
                    Text(
                        text = ticket.vehiclePlate,
                        fontSize = 14.sp,
                        fontWeight = FontWeight.SemiBold,
                        color = ExecutivePrimaryGreen
                    )
                }
            }

            Spacer(modifier = Modifier.height(16.dp))

            // Card 2: Informations de l'Intervention
            Surface(
                modifier = Modifier
                    .fillMaxWidth()
                    .shadow(elevation = 2.dp, shape = RoundedCornerShape(18.dp)),
                shape = RoundedCornerShape(18.dp),
                color = ExecutiveSurface,
                border = androidx.compose.foundation.BorderStroke(1.dp, ExecutiveBorder)
            ) {
                Column(modifier = Modifier.padding(18.dp)) {
                    Text(
                        text = "Informations de l'Intervention",
                        fontSize = 18.sp,
                        fontWeight = FontWeight.Bold,
                        color = ExecutiveTextPrimary
                    )

                    Spacer(modifier = Modifier.height(14.dp))

                    DetailRow("Type", ticket.serviceItem)
                    DetailRow("Titre", ticket.title ?: "N/A")
                    DetailRow("Date", ticket.scheduledDate)
                    DetailRow("Kilométrage", "${ticket.mileage ?: "N/A"} km")
                    DetailRow("Garage", ticket.location ?: "N/A")
                    DetailRow("Technicien", ticket.technician)
                    DetailRow("N° Facture", ticket.invoice_number ?: "N/A")
                }
            }

            Spacer(modifier = Modifier.height(16.dp))

            // Détails Vidange (Si applicable)
            if (ticket.serviceItem == "Vidange") {
                Surface(
                    modifier = Modifier
                        .fillMaxWidth()
                        .shadow(elevation = 2.dp, shape = RoundedCornerShape(18.dp)),
                    shape = RoundedCornerShape(18.dp),
                    color = ExecutiveSurface,
                    border = androidx.compose.foundation.BorderStroke(1.dp, ExecutiveBorder)
                ) {
                    Column(modifier = Modifier.padding(18.dp)) {
                        Text(
                            text = "Détails Vidange",
                            fontSize = 18.sp,
                            fontWeight = FontWeight.Bold,
                            color = ExecutiveTextPrimary
                        )
                        Spacer(modifier = Modifier.height(14.dp))
                        DetailRow("Marque Huile", ticket.oil_brand ?: "N/A")
                        DetailRow("Viscosité", ticket.oil_viscosity ?: "N/A")
                        DetailRow("Quantité", "${ticket.oil_quantity ?: 0.0} L")
                        DetailRow("Filtre Huile", if(ticket.oil_filter_changed) "Oui" else "Non")
                        DetailRow("Filtre Air", if(ticket.air_filter_changed) "Oui" else "Non")
                        DetailRow("Filtre Carburant", if(ticket.fuel_filter_changed) "Oui" else "Non")
                        DetailRow("Filtre Habitacle", if(ticket.cabin_filter_changed) "Oui" else "Non")
                    }
                }
                Spacer(modifier = Modifier.height(16.dp))
            }

            // Détails Problème
            if (ticket.description.isNotBlank() || !ticket.diagnosis.isNullOrBlank() || !ticket.repair_description.isNullOrBlank()) {
                Surface(
                    modifier = Modifier
                        .fillMaxWidth()
                        .shadow(elevation = 2.dp, shape = RoundedCornerShape(18.dp)),
                    shape = RoundedCornerShape(18.dp),
                    color = ExecutiveSurface,
                    border = androidx.compose.foundation.BorderStroke(1.dp, ExecutiveBorder)
                ) {
                    Column(modifier = Modifier.padding(18.dp)) {
                        Text(
                            text = "Rapport Technique",
                            fontSize = 18.sp,
                            fontWeight = FontWeight.Bold,
                            color = ExecutiveTextPrimary
                        )
                        Spacer(modifier = Modifier.height(14.dp))

                        if (ticket.description.isNotBlank()) {
                            Text("Problème:", fontWeight = FontWeight.Bold, fontSize = 14.sp)
                            Text(ticket.description, fontSize = 14.sp)
                            Spacer(modifier = Modifier.height(8.dp))
                        }
                        if (!ticket.diagnosis.isNullOrBlank()) {
                            Text("Diagnostic:", fontWeight = FontWeight.Bold, fontSize = 14.sp)
                            Text(ticket.diagnosis!!, fontSize = 14.sp)
                            Spacer(modifier = Modifier.height(8.dp))
                        }
                        if (!ticket.repair_description.isNullOrBlank()) {
                            Text("Réparation:", fontWeight = FontWeight.Bold, fontSize = 14.sp)
                            Text(ticket.repair_description!!, fontSize = 14.sp)
                        }
                    }
                }
                Spacer(modifier = Modifier.height(16.dp))
            }

            // Pièces et Facturation
            Surface(
                modifier = Modifier
                    .fillMaxWidth()
                    .shadow(elevation = 2.dp, shape = RoundedCornerShape(18.dp)),
                shape = RoundedCornerShape(18.dp),
                color = ExecutiveSurface,
                border = androidx.compose.foundation.BorderStroke(1.dp, ExecutiveBorder)
            ) {
                Column(modifier = Modifier.padding(18.dp)) {
                    Text(
                        text = "Facturation",
                        fontSize = 18.sp,
                        fontWeight = FontWeight.Bold,
                        color = ExecutiveTextPrimary
                    )
                    Spacer(modifier = Modifier.height(14.dp))

                    if (ticket.parts.isNotEmpty()) {
                        Text("Pièces de rechange:", fontWeight = FontWeight.SemiBold, fontSize = 14.sp)
                        ticket.parts.forEach { part ->
                            Row(
                                modifier = Modifier.fillMaxWidth().padding(vertical = 4.dp),
                                horizontalArrangement = Arrangement.SpaceBetween
                            ) {
                                Text("- ${part.part_name} (x${part.quantity})", fontSize = 14.sp)
                                Text("${part.total_price} DH", fontSize = 14.sp, fontWeight = FontWeight.SemiBold)
                            }
                        }
                        Spacer(modifier = Modifier.height(8.dp))
                    }

                    DetailRow("Coût Pièces", "${ticket.parts_cost} DH")
                    DetailRow("Main d'œuvre", "${ticket.labor_cost} DH")
                    DetailRow("Autres Frais", "${ticket.other_cost} DH")

                    HorizontalDivider(modifier = Modifier.padding(vertical = 10.dp), thickness = 1.dp)

                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.SpaceBetween
                    ) {
                        Text("Total", fontSize = 16.sp, fontWeight = FontWeight.Bold)
                        Text(
                            text = "${ticket.actual_cost ?: ticket.estimatedCost} DH",
                            fontSize = 16.sp,
                            fontWeight = FontWeight.Bold,
                            color = ExecutivePrimaryGreen
                        )
                    }
                }
            }

            Spacer(modifier = Modifier.height(16.dp))

            Text(
                text = "Modification de l'historique recommandée via la plateforme bureau.",
                fontSize = 12.sp,
                color = ExecutiveTextTertiary,
                modifier = Modifier.padding(8.dp)
            )
        }
    }
}

@Composable
fun DetailRow(label: String, value: String) {
    Row(
        modifier = Modifier.fillMaxWidth().padding(vertical = 4.dp),
        horizontalArrangement = Arrangement.SpaceBetween
    ) {
        Text(
            text = label,
            fontSize = 14.sp,
            fontWeight = FontWeight.SemiBold,
            color = ExecutiveTextSecondary
        )
        Text(
            text = value,
            fontSize = 14.sp,
            fontWeight = FontWeight.Medium,
            color = ExecutiveTextPrimary
        )
    }
}
