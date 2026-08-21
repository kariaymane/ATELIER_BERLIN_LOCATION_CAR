package com.example.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.DirectionsCar
import androidx.compose.material.icons.filled.Build
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import coil.compose.AsyncImage
import com.example.data.model.MaintenanceStep
import com.example.data.model.MaintenanceTicket
import com.example.data.model.Reservation
import com.example.data.model.Vehicle
import com.example.ui.theme.*

@Composable
fun VehicleCard(
    vehicle: Vehicle,
    onClick: () -> Unit,
    modifier: Modifier = Modifier
) {
    Surface(
        modifier = modifier
            .fillMaxWidth()
            .shadow(elevation = 2.dp, shape = RoundedCornerShape(18.dp))
            .clickable { onClick() },
        shape = RoundedCornerShape(18.dp),
        color = ExecutiveSurface,
        border = androidx.compose.foundation.BorderStroke(1.dp, ExecutiveBorder)
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(12.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            // Vehicle Thumbnail
            Box(
                modifier = Modifier
                    .size(90.dp, 75.dp)
                    .clip(RoundedCornerShape(12.dp))
                    .background(ExecutiveSurfaceVariant),
                contentAlignment = Alignment.Center
            ) {
                if (vehicle.imageUrl.isNotBlank()) {
                    AsyncImage(
                        model = vehicle.imageUrl,
                        contentDescription = vehicle.fullName,
                        contentScale = ContentScale.Crop,
                        modifier = Modifier.fillMaxSize()
                    )
                } else {
                    Icon(
                        imageVector = Icons.Default.DirectionsCar,
                        contentDescription = null,
                        tint = ExecutiveTextTertiary,
                        modifier = Modifier.size(36.dp)
                    )
                }
            }

            Spacer(modifier = Modifier.width(14.dp))

            // Vehicle Info
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    text = vehicle.fullName,
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.Bold,
                    color = ExecutiveTextPrimary,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis
                )
                Spacer(modifier = Modifier.height(2.dp))
                Text(
                    text = vehicle.plate,
                    style = MaterialTheme.typography.bodySmall,
                    color = ExecutiveTextSecondary
                )
                Text(
                    text = "${vehicle.year}",
                    style = MaterialTheme.typography.bodySmall,
                    color = ExecutiveTextTertiary
                )
            }

            // Price & Status
            Column(
                horizontalAlignment = Alignment.End,
                verticalArrangement = Arrangement.Center
            ) {
                Row(verticalAlignment = Alignment.Bottom) {
                    Text(
                        text = "${vehicle.dailyRate} DH",
                        fontSize = 15.sp,
                        fontWeight = FontWeight.Bold,
                        color = ExecutiveTextPrimary
                    )
                    Text(
                        text = " / jour",
                        fontSize = 11.sp,
                        color = ExecutiveTextSecondary,
                        modifier = Modifier.padding(bottom = 1.dp)
                    )
                }
                Spacer(modifier = Modifier.height(8.dp))
                VehicleStatusBadge(status = vehicle.status)
            }
        }
    }
}

@Composable
fun ReservationCard(
    reservation: Reservation,
    onClick: () -> Unit,
    modifier: Modifier = Modifier
) {
    Surface(
        modifier = modifier
            .fillMaxWidth()
            .shadow(elevation = 2.dp, shape = RoundedCornerShape(18.dp))
            .clickable { onClick() },
        shape = RoundedCornerShape(18.dp),
        color = ExecutiveSurface,
        border = androidx.compose.foundation.BorderStroke(1.dp, ExecutiveBorder)
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(16.dp)
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically
            ) {
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    modifier = Modifier.weight(1f)
                ) {
                    Text(
                        text = "Client : ",
                        fontSize = 14.sp,
                        fontWeight = FontWeight.Bold,
                        color = ExecutiveTextPrimary
                    )
                    Text(
                        text = reservation.clientName,
                        fontSize = 14.sp,
                        color = ExecutiveTextPrimary,
                        fontWeight = FontWeight.Medium,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis
                    )
                }
                ReservationStatusBadge(status = reservation.status)
            }

            Spacer(modifier = Modifier.height(8.dp))

            Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically
            ) {
                Text(
                    text = "Véhicule : ",
                    fontSize = 13.sp,
                    fontWeight = FontWeight.SemiBold,
                    color = ExecutiveTextSecondary
                )
                Text(
                    text = reservation.vehicleName,
                    fontSize = 13.sp,
                    color = ExecutiveTextPrimary,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                    modifier = Modifier.weight(1f)
                )
                Icon(
                    imageVector = Icons.Default.DirectionsCar,
                    contentDescription = null,
                    tint = ExecutiveTextTertiary,
                    modifier = Modifier.size(16.dp)
                )
            }

            Spacer(modifier = Modifier.height(4.dp))

            Row(modifier = Modifier.fillMaxWidth()) {
                Text(
                    text = "Dates : ",
                    fontSize = 13.sp,
                    fontWeight = FontWeight.SemiBold,
                    color = ExecutiveTextSecondary
                )
                Text(
                    text = "${reservation.startDate} - ${reservation.endDate}",
                    fontSize = 13.sp,
                    color = ExecutiveTextPrimary
                )
            }

            Spacer(modifier = Modifier.height(4.dp))

            Row(modifier = Modifier.fillMaxWidth()) {
                Text(
                    text = "Prix Total : ",
                    fontSize = 13.sp,
                    fontWeight = FontWeight.SemiBold,
                    color = ExecutiveTextSecondary
                )
                Text(
                    text = "${reservation.totalAmount} DH",
                    fontSize = 13.sp,
                    fontWeight = FontWeight.Bold,
                    color = ExecutivePrimaryGreen
                )
            }
        }
    }
}

@Composable
fun MaintenanceCard(
    ticket: MaintenanceTicket,
    onClick: () -> Unit,
    modifier: Modifier = Modifier
) {
    val steps = listOf(
        MaintenanceStep.DIAGNOSTIC,
        MaintenanceStep.REPARATION,
        MaintenanceStep.CONTROLE,
        MaintenanceStep.TERMINEE
    )

    val currentStepIndex = when (ticket.step) {
        MaintenanceStep.DIAGNOSTIC -> 0
        MaintenanceStep.REPARATION -> 1
        MaintenanceStep.CONTROLE -> 2
        MaintenanceStep.TERMINEE -> 3
        else -> 0
    }

    Surface(
        modifier = modifier
            .fillMaxWidth()
            .shadow(elevation = 2.dp, shape = RoundedCornerShape(18.dp))
            .clickable { onClick() },
        shape = RoundedCornerShape(18.dp),
        color = ExecutiveSurface,
        border = androidx.compose.foundation.BorderStroke(1.dp, ExecutiveBorder)
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(16.dp)
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically
            ) {
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    modifier = Modifier.weight(1f)
                ) {
                    Icon(
                        imageVector = Icons.Default.DirectionsCar,
                        contentDescription = null,
                        tint = ExecutiveTextSecondary,
                        modifier = Modifier.size(18.dp)
                    )
                    Spacer(modifier = Modifier.width(8.dp))
                    Text(
                        text = "Véhicule : ${ticket.vehicleName}",
                        fontSize = 14.sp,
                        fontWeight = FontWeight.Bold,
                        color = ExecutiveTextPrimary,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis
                    )
                }
                MaintenanceStepBadge(step = ticket.step)
            }

            Spacer(modifier = Modifier.height(6.dp))

            Row(verticalAlignment = Alignment.CenterVertically) {
                Icon(
                    imageVector = Icons.Default.Build,
                    contentDescription = null,
                    tint = ExecutiveTextSecondary,
                    modifier = Modifier.size(16.dp)
                )
                Spacer(modifier = Modifier.width(8.dp))
                Text(
                    text = "${ticket.serviceItem} : ${ticket.description.ifBlank { "Contrôle standard" }}",
                    fontSize = 13.sp,
                    color = ExecutiveTextPrimary,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis
                )
            }

            Spacer(modifier = Modifier.height(4.dp))

            Text(
                text = "Date : ${ticket.scheduledDate}",
                fontSize = 12.sp,
                color = ExecutiveTextSecondary
            )

            Spacer(modifier = Modifier.height(14.dp))

            // Multi-step progress line matching screenshot 10
            Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.SpaceBetween
            ) {
                steps.forEachIndexed { index, step ->
                    val isDone = index <= currentStepIndex

                    Column(
                        horizontalAlignment = Alignment.CenterHorizontally,
                        modifier = Modifier.weight(1f)
                    ) {
                        Box(
                            modifier = Modifier
                                .size(22.dp)
                                .clip(CircleShape)
                                .background(if (isDone) ExecutivePrimaryGreen else ExecutiveSurfaceVariant)
                                .border(
                                    1.dp,
                                    if (isDone) ExecutivePrimaryGreen else ExecutiveBorder,
                                    CircleShape
                                ),
                            contentAlignment = Alignment.Center
                        ) {
                            if (isDone) {
                                Icon(
                                    imageVector = Icons.Default.Check,
                                    contentDescription = null,
                                    tint = Color.White,
                                    modifier = Modifier.size(12.dp)
                                )
                            }
                        }

                        Spacer(modifier = Modifier.height(4.dp))

                        Text(
                            text = when (step) {
                                MaintenanceStep.DIAGNOSTIC -> "Diagnostic"
                                MaintenanceStep.REPARATION -> "Réparation"
                                MaintenanceStep.CONTROLE -> "Tests"
                                MaintenanceStep.TERMINEE -> "Finalisé"
                                else -> step.label
                            },
                            fontSize = 10.sp,
                            fontWeight = if (isDone) FontWeight.Bold else FontWeight.Normal,
                            color = if (isDone) ExecutivePrimaryGreen else ExecutiveTextTertiary,
                            maxLines = 1
                        )
                    }
                }
            }
        }
    }
}
