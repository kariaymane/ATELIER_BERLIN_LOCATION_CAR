package com.example.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ArrowBack
import androidx.compose.material.icons.filled.DateRange
import androidx.compose.material.icons.filled.DirectionsCar
import androidx.compose.material.icons.filled.Person
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import coil.compose.AsyncImage
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import coil.compose.SubcomposeAsyncImage
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.foundation.layout.Box
import com.example.data.model.Reservation
import com.example.data.model.ReservationStatus
import com.example.ui.components.ExecutiveButton
import com.example.ui.components.ReservationStatusBadge
import com.example.ui.theme.*
import com.example.ui.viewmodel.FleetViewModel

@Composable
fun ReservationDetailScreen(
    reservationId: String,
    viewModel: FleetViewModel,
    modifier: Modifier = Modifier
) {
    val reservations by viewModel.reservations.collectAsState()
    val reservation = remember(reservations, reservationId) {
        reservations.find { it.id == reservationId }
    }

    val scrollState = rememberScrollState()

    if (reservation == null) {
        Box(
            modifier = modifier
                .fillMaxSize()
                .background(ExecutiveBackground),
            contentAlignment = Alignment.Center
        ) {
            Column(horizontalAlignment = Alignment.CenterHorizontally) {
                Text(
                    text = "Réservation introuvable",
                    style = MaterialTheme.typography.titleMedium,
                    color = ExecutiveTextSecondary
                )
                Spacer(modifier = Modifier.height(12.dp))
                ExecutiveButton(
                    text = "Retour",
                    onClick = { viewModel.navigateBack() },
                    modifier = Modifier.width(140.dp)
                )
            }
        }
        return
    }

    Column(
        modifier = modifier
            .fillMaxSize()
            .background(ExecutiveBackground)
            .statusBarsPadding()
    ) {
        // Top Header
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 16.dp, vertical = 12.dp),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically
        ) {
            IconButton(
                onClick = { viewModel.navigateBack() },
                modifier = Modifier
                    .size(40.dp)
                    .clip(CircleShape)
                    .background(ExecutiveSurface)
                    .border(1.dp, ExecutiveBorder, CircleShape)
            ) {
                Icon(
                    imageVector = Icons.Default.ArrowBack,
                    contentDescription = "Retour",
                    tint = ExecutiveTextPrimary,
                    modifier = Modifier.size(20.dp)
                )
            }

            Text(
                text = "Détails Réservation",
                fontSize = 18.sp,
                fontFamily = FontFamily.Serif,
                fontWeight = FontWeight.SemiBold,
                color = ExecutiveTextPrimary
            )

            ReservationStatusBadge(status = reservation.status)
        }

        Column(
            modifier = Modifier
                .fillMaxSize()
                .verticalScroll(scrollState)
                .padding(horizontal = 20.dp)
                .padding(bottom = 32.dp)
        ) {
            // Card 1: Informations Client
            Surface(
                modifier = Modifier
                    .fillMaxWidth()
                    .shadow(elevation = 2.dp, shape = RoundedCornerShape(18.dp)),
                shape = RoundedCornerShape(18.dp),
                color = ExecutiveSurface,
                border = androidx.compose.foundation.BorderStroke(1.dp, ExecutiveBorder)
            ) {
                Column(modifier = Modifier.padding(18.dp)) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Icon(
                            imageVector = Icons.Default.Person,
                            contentDescription = null,
                            tint = ExecutiveTextPrimary,
                            modifier = Modifier.size(20.dp)
                        )
                        Spacer(modifier = Modifier.width(8.dp))
                        Text(
                            text = "Informations Client",
                            fontSize = 18.sp,
                            fontWeight = FontWeight.Bold,
                            color = ExecutiveTextPrimary
                        )
                    }

                    Spacer(modifier = Modifier.height(12.dp))

                    DetailItem(label = "Nom", value = reservation.clientName)
                    DetailItem(label = "Téléphone", value = reservation.clientPhone)
                    if (reservation.clientEmail.isNotBlank()) {
                        DetailItem(label = "Email", value = reservation.clientEmail)
                    }
                    DetailItem(label = "Statut Paiement", value = reservation.paymentStatus)
                }
            }

            Spacer(modifier = Modifier.height(16.dp))

            // Card 2: Résumé Technique du Véhicule
            Surface(
                modifier = Modifier
                    .fillMaxWidth()
                    .shadow(elevation = 2.dp, shape = RoundedCornerShape(18.dp)),
                shape = RoundedCornerShape(18.dp),
                color = ExecutiveSurface,
                border = androidx.compose.foundation.BorderStroke(1.dp, ExecutiveBorder)
            ) {
                Column(modifier = Modifier.padding(18.dp)) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Icon(
                            imageVector = Icons.Default.DirectionsCar,
                            contentDescription = null,
                            tint = ExecutiveTextPrimary,
                            modifier = Modifier.size(20.dp)
                        )
                        Spacer(modifier = Modifier.width(8.dp))
                        Text(
                            text = "Résumé Technique du Véhicule",
                            fontSize = 18.sp,
                            fontWeight = FontWeight.Bold,
                            color = ExecutiveTextPrimary
                        )
                    }

                    Spacer(modifier = Modifier.height(14.dp))

                    Row(modifier = Modifier.fillMaxWidth()) {
                        Box(
                            modifier = Modifier
                                .size(110.dp, 85.dp)
                                .clip(RoundedCornerShape(12.dp))
                                .background(ExecutiveSurfaceVariant),
                            contentAlignment = Alignment.Center
                        ) {
                            SubcomposeAsyncImage(
                                model = reservation.vehicleImageUrl.ifBlank { null },
                                contentDescription = reservation.vehicleName,
                                contentScale = ContentScale.Crop,
                                modifier = Modifier.fillMaxSize(),
                                loading = {
                                    Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                                        CircularProgressIndicator(modifier = Modifier.size(24.dp), color = ExecutivePrimaryGreen)
                                    }
                                },
                                error = {
                                    Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                                        Icon(
                                            imageVector = Icons.Default.DirectionsCar,
                                            contentDescription = null,
                                            tint = ExecutiveTextTertiary,
                                            modifier = Modifier.size(40.dp)
                                        )
                                    }
                                }
                            )
                        }

                        Spacer(modifier = Modifier.width(16.dp))

                        Column(modifier = Modifier.weight(1f)) {
                            Text(
                                text = reservation.vehicleName,
                                fontSize = 17.sp,
                                fontWeight = FontWeight.Bold,
                                color = ExecutiveTextPrimary
                            )
                            Spacer(modifier = Modifier.height(4.dp))
                            Text(
                                text = "Immat : ${reservation.vehiclePlate}",
                                fontSize = 13.sp,
                                color = ExecutiveTextSecondary
                            )
                            Spacer(modifier = Modifier.height(4.dp))
                            Text(
                                text = "${reservation.dailyPrice} DH / jour",
                                fontSize = 14.sp,
                                fontWeight = FontWeight.Bold,
                                color = ExecutivePrimaryGreen
                            )
                        }
                    }
                }
            }

            Spacer(modifier = Modifier.height(16.dp))

            // Card 3: Période & Conditions
            Surface(
                modifier = Modifier
                    .fillMaxWidth()
                    .shadow(elevation = 2.dp, shape = RoundedCornerShape(18.dp)),
                shape = RoundedCornerShape(18.dp),
                color = ExecutiveSurface,
                border = androidx.compose.foundation.BorderStroke(1.dp, ExecutiveBorder)
            ) {
                Column(modifier = Modifier.padding(18.dp)) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Icon(
                            imageVector = Icons.Default.DateRange,
                            contentDescription = null,
                            tint = ExecutiveTextPrimary,
                            modifier = Modifier.size(20.dp)
                        )
                        Spacer(modifier = Modifier.width(8.dp))
                        Text(
                            text = "Période & Tarification",
                            fontSize = 18.sp,
                            fontWeight = FontWeight.Bold,
                            color = ExecutiveTextPrimary
                        )
                    }

                    Spacer(modifier = Modifier.height(12.dp))

                    DetailItem(label = "Date de Début", value = reservation.startDate)
                    DetailItem(label = "Date de Fin", value = reservation.endDate)
                    DetailItem(label = "Durée", value = "${reservation.numDays} jour(s)")
                    DetailItem(label = "Lieu Prise en charge", value = reservation.pickupLocation)
                    DetailItem(label = "Lieu Restitution", value = reservation.returnLocation)

                    HorizontalDivider(
                        modifier = Modifier.padding(vertical = 10.dp),
                        thickness = 1.dp,
                        color = ExecutiveBorder
                    )

                    DetailItem(label = "Dépôt de Garantie", value = "${reservation.deposit} DH")
                    DetailItem(label = "Montant Total", value = "${reservation.totalAmount} DH")
                }
            }

            Spacer(modifier = Modifier.height(16.dp))

            if (reservation.notes.isNotBlank()) {
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
                            text = "Remarques & Notes",
                            fontSize = 15.sp,
                            fontWeight = FontWeight.Bold,
                            color = ExecutiveTextPrimary
                        )
                        Spacer(modifier = Modifier.height(6.dp))
                        Text(
                            text = reservation.notes,
                            fontSize = 13.sp,
                            color = ExecutiveTextSecondary
                        )
                    }
                }
                Spacer(modifier = Modifier.height(16.dp))
            }

            Text(
                text = "Lecture seule • Gestion administrative depuis le logiciel Desktop.",
                fontSize = 12.sp,
                color = ExecutiveTextTertiary,
                modifier = Modifier.padding(8.dp)
            )
        }
    }
}

@Composable
private fun DetailItem(label: String, value: String) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = 4.dp),
        horizontalArrangement = Arrangement.SpaceBetween
    ) {
        Text(
            text = "$label :",
            fontSize = 14.sp,
            fontWeight = FontWeight.SemiBold,
            color = ExecutiveTextSecondary
        )
        Text(
            text = value,
            fontSize = 14.sp,
            color = ExecutiveTextPrimary,
            fontWeight = FontWeight.Medium
        )
    }
}
