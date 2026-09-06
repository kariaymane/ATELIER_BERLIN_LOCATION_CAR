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
import com.example.data.model.MaintenanceTicket
import com.example.data.model.Reservation
import com.example.data.model.ReservationStatus
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
                if (reservation.status == ReservationStatus.ANNULEE &&
                    reservation.cancellationReason?.contains("MAINTENANCE", ignoreCase = true) == true) {
                    StatusBadge(
                        text = "Annulée — Maintenance",
                        backgroundColor = StatusRedBg,
                        textColor = StatusRedText,
                        dotColor = StatusRedDot
                    )
                } else {
                    ReservationStatusBadge(status = reservation.status)
                }
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
    val isCompleted = ticket.isCompleted
    val isCancelled = ticket.isCancelled
    val statusText = ticket.effectiveStatusDisplay

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
                StatusBadge(
                    text = statusText,
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

            Spacer(modifier = Modifier.height(8.dp))

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

            Spacer(modifier = Modifier.height(6.dp))

            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically
            ) {
                // The maintenance PERIOD is what defines its status, so the
                // card shows both edges. It wraps instead of being clipped and
                // yields its width to the cost on the right.
                Text(
                    text = if (ticket.scheduledEndDate.isNotBlank())
                        "Du ${ticket.scheduledDate} au ${ticket.scheduledEndDate}"
                    else
                        "Début : ${ticket.scheduledDate}",
                    fontSize = 12.sp,
                    color = ExecutiveTextSecondary,
                    modifier = Modifier.weight(1f, fill = false)
                )
                Spacer(modifier = Modifier.width(8.dp))
                val cost = ticket.actual_cost ?: ticket.estimatedCost.toDouble()
                if (cost > 0.0) {
                    Text(
                        text = "${String.format("%.0f", cost)} DH",
                        fontSize = 13.sp,
                        fontWeight = FontWeight.Bold,
                        color = ExecutivePrimaryGreen
                    )
                }
            }
        }
    }
}
