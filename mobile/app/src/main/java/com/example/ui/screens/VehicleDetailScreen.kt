package com.example.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.clickable
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ArrowBack
import androidx.compose.material.icons.filled.DirectionsCar
import androidx.compose.material.icons.filled.Share
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import coil.compose.AsyncImage
import com.example.data.model.Vehicle
import com.example.data.model.VehicleStatus
import com.example.ui.components.ExecutiveButton
import com.example.ui.components.VehicleStatusBadge
import com.example.ui.theme.*
import com.example.ui.viewmodel.FleetViewModel
import java.text.NumberFormat
import java.util.Locale

@Composable
fun VehicleDetailScreen(
    vehicleId: String,
    viewModel: FleetViewModel,
    modifier: Modifier = Modifier
) {
    val vehicles by viewModel.vehicles.collectAsState()
    val vehicle = remember(vehicles, vehicleId) {
        vehicles.find { it.id == vehicleId }
    }

    val scrollState = rememberScrollState()
    val numberFormat = remember { NumberFormat.getNumberInstance(Locale.FRENCH) }

    if (vehicle == null) {
        Box(
            modifier = modifier
                .fillMaxSize()
                .background(ExecutiveBackground),
            contentAlignment = Alignment.Center
        ) {
            Column(horizontalAlignment = Alignment.CenterHorizontally) {
                Text(
                    text = "Véhicule introuvable",
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
        // Top Navigation Header
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
                text = "ATELIER BERLIN LOCATION CAR",
                fontSize = 20.sp,
                fontFamily = FontFamily.Serif,
                fontWeight = FontWeight.SemiBold,
                color = ExecutiveTextPrimary
            )

            // Spacer or empty box to balance the ArrowBack on the left
            Box(modifier = Modifier.size(40.dp))
        }

        Column(
            modifier = Modifier
                .fillMaxSize()
                .verticalScroll(scrollState)
                .padding(horizontal = 20.dp)
                .padding(bottom = 32.dp)
        ) {
            // Status Pill Centered
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(vertical = 8.dp),
                contentAlignment = Alignment.Center
            ) {
                VehicleStatusBadge(status = vehicle.status)
            }

            Spacer(modifier = Modifier.height(8.dp))

            // Vehicle Title
            Text(
                text = vehicle.fullName,
                fontSize = 26.sp,
                fontWeight = FontWeight.Bold,
                fontFamily = FontFamily.Serif,
                color = ExecutiveTextPrimary,
                textAlign = TextAlign.Center,
                modifier = Modifier.fillMaxWidth()
            )

            Spacer(modifier = Modifier.height(4.dp))

            Text(
                text = "Plaque : ${vehicle.plate} • Catégorie : ${vehicle.category}",
                fontSize = 13.sp,
                color = ExecutiveTextSecondary,
                textAlign = TextAlign.Center,
                modifier = Modifier.fillMaxWidth()
            )

            Spacer(modifier = Modifier.height(18.dp))

            val imageUrls = remember(vehicle.images, vehicle.imageUrl) {
                if (vehicle.images.isNotEmpty()) vehicle.images
                else if (vehicle.imageUrl.isBlank()) emptyList()
                else vehicle.imageUrl.split(",").map { it.trim() }.filter { it.isNotBlank() }
            }
            var selectedImageIndex by remember { mutableIntStateOf(0) }
            val currentPhotoUrl = imageUrls.getOrNull(selectedImageIndex) ?: vehicle.imageUrl

            // Hero Vehicle Photo
            Surface(
                modifier = Modifier
                    .fillMaxWidth()
                    .height(230.dp)
                    .shadow(elevation = 3.dp, shape = RoundedCornerShape(20.dp)),
                shape = RoundedCornerShape(20.dp),
                color = ExecutiveSurfaceVariant
            ) {
                if (currentPhotoUrl.isNotBlank()) {
                    AsyncImage(
                        model = currentPhotoUrl,
                        contentDescription = vehicle.fullName,
                        contentScale = ContentScale.Crop,
                        modifier = Modifier.fillMaxSize()
                    )
                } else {
                    Box(
                        modifier = Modifier.fillMaxSize(),
                        contentAlignment = Alignment.Center
                    ) {
                        Icon(
                            imageVector = Icons.Default.DirectionsCar,
                            contentDescription = null,
                            tint = ExecutiveTextTertiary,
                            modifier = Modifier.size(72.dp)
                        )
                    }
                }
            }

            // Thumbnail Gallery if multiple photos exist
            if (imageUrls.size > 1) {
                Spacer(modifier = Modifier.height(10.dp))
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(horizontal = 4.dp),
                    horizontalArrangement = Arrangement.spacedBy(8.dp)
                ) {
                    imageUrls.forEachIndexed { index, photoUrl ->
                        val isSelected = index == selectedImageIndex
                        Surface(
                            modifier = Modifier
                                .size(56.dp)
                                .clickable { selectedImageIndex = index }
                                .border(
                                    width = if (isSelected) 2.dp else 1.dp,
                                    color = if (isSelected) ExecutivePrimaryGreen else ExecutiveBorder,
                                    shape = RoundedCornerShape(10.dp)
                                ),
                            shape = RoundedCornerShape(10.dp),
                            color = ExecutiveSurfaceVariant
                        ) {
                            AsyncImage(
                                model = photoUrl,
                                contentDescription = "Photo ${index + 1}",
                                contentScale = ContentScale.Crop,
                                modifier = Modifier.fillMaxSize()
                            )
                        }
                    }
                }
            }

            Spacer(modifier = Modifier.height(24.dp))

            // Description / Note
            Text(
                text = "Description & Remarques",
                fontSize = 17.sp,
                fontWeight = FontWeight.SemiBold,
                fontFamily = FontFamily.Serif,
                color = ExecutiveTextPrimary
            )
            Spacer(modifier = Modifier.height(6.dp))
            Text(
                text = vehicle.description,
                fontSize = 14.sp,
                color = ExecutiveTextSecondary,
                lineHeight = 20.sp
            )

            Spacer(modifier = Modifier.height(24.dp))

            // Specs Section
            Text(
                text = "Caractéristiques Techniques",
                fontSize = 17.sp,
                fontWeight = FontWeight.SemiBold,
                fontFamily = FontFamily.Serif,
                color = ExecutiveTextPrimary
            )

            HorizontalDivider(
                modifier = Modifier.padding(vertical = 10.dp),
                thickness = 1.dp,
                color = ExecutiveBorder
            )

            SpecRow(label = "Année", value = "${vehicle.year}")
            SpecRow(label = "Kilométrage", value = "${numberFormat.format(vehicle.mileage)} km")
            SpecRow(label = "Carburant", value = vehicle.fuelType.ifBlank { "N/A" })
            SpecRow(label = "Transmission", value = vehicle.transmission.ifBlank { "N/A" })
            if (vehicle.power.isNotBlank()) {
                SpecRow(label = "Puissance", value = vehicle.power)
            }
            SpecRow(label = "Couleur", value = vehicle.color.ifBlank { "N/A" })
            if (vehicle.vin.isNotBlank()) {
                SpecRow(label = "Numéro VIN", value = vehicle.vin)
            }

            Spacer(modifier = Modifier.height(24.dp))

            // Financial & Rates Overview (Read-Only)
            Text(
                text = "Conditions Tarifaires",
                fontSize = 17.sp,
                fontWeight = FontWeight.SemiBold,
                fontFamily = FontFamily.Serif,
                color = ExecutiveTextPrimary
            )

            HorizontalDivider(
                modifier = Modifier.padding(vertical = 10.dp),
                thickness = 1.dp,
                color = ExecutiveBorder
            )

            SpecRow(label = "Tarif Journalier", value = "${vehicle.dailyRate} DH", isBold = true)
            SpecRow(label = "Tarif Hebdomadaire", value = "${vehicle.dailyRate * 6} DH")
            SpecRow(label = "Dépôt de Garantie", value = "${vehicle.deposit} DH")

            Spacer(modifier = Modifier.height(20.dp))
        }
    }
}

@Composable
private fun SpecRow(
    label: String,
    value: String,
    isBold: Boolean = false
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = 7.dp),
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.CenterVertically
    ) {
        Text(
            text = label,
            fontSize = 15.sp,
            color = ExecutiveTextSecondary,
            fontWeight = FontWeight.Normal
        )
        Text(
            text = value,
            fontSize = 15.sp,
            color = ExecutiveTextPrimary,
            fontWeight = if (isBold) FontWeight.Bold else FontWeight.Medium
        )
    }
    HorizontalDivider(
        thickness = 0.5.dp,
        color = ExecutiveBorderLight
    )
}
