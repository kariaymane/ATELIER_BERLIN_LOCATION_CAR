package com.example.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.example.data.model.MaintenanceStep
import com.example.data.model.ReservationStatus
import com.example.data.model.VehicleStatus
import com.example.ui.theme.*

@Composable
fun StatusBadge(
    text: String,
    backgroundColor: Color,
    textColor: Color,
    dotColor: Color,
    modifier: Modifier = Modifier
) {
    Row(
        modifier = modifier
            .clip(RoundedCornerShape(16.dp))
            .background(backgroundColor)
            .border(1.dp, dotColor.copy(alpha = 0.35f), RoundedCornerShape(16.dp))
            .padding(horizontal = 10.dp, vertical = 5.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.Center
    ) {
        Box(
            modifier = Modifier
                .size(7.dp)
                .clip(CircleShape)
                .background(dotColor)
        )
        Spacer(modifier = Modifier.width(6.dp))
        Text(
            text = text,
            color = textColor,
            fontSize = 12.sp,
            fontWeight = FontWeight.SemiBold,
            maxLines = 1
        )
    }
}

@Composable
fun VehicleStatusBadge(status: VehicleStatus, modifier: Modifier = Modifier) {
    when (status) {
        VehicleStatus.DISPONIBLE -> StatusBadge(
            text = status.label,
            backgroundColor = StatusGreenBg,
            textColor = StatusGreenText,
            dotColor = StatusGreenDot,
            modifier = modifier
        )
        VehicleStatus.EN_LOCATION -> StatusBadge(
            text = status.label,
            backgroundColor = StatusOrangeBg,
            textColor = StatusOrangeText,
            dotColor = StatusOrangeDot,
            modifier = modifier
        )
        VehicleStatus.RESERVEE -> StatusBadge(
            text = status.label,
            backgroundColor = StatusGoldBg,
            textColor = StatusGoldText,
            dotColor = StatusGoldDot,
            modifier = modifier
        )
        VehicleStatus.MAINTENANCE -> StatusBadge(
            text = status.label,
            backgroundColor = StatusRedBg,
            textColor = StatusRedText,
            dotColor = StatusRedDot,
            modifier = modifier
        )
        VehicleStatus.VENDU, VehicleStatus.INACTIF -> StatusBadge(
            text = status.label,
            backgroundColor = StatusGrayBg,
            textColor = StatusGrayText,
            dotColor = StatusGrayDot,
            modifier = modifier
        )
    }
}

@Composable
fun ReservationStatusBadge(status: ReservationStatus, modifier: Modifier = Modifier) {
    when (status) {
        ReservationStatus.EN_COURS -> StatusBadge(
            text = status.label,
            backgroundColor = StatusGreenBg,
            textColor = StatusGreenText,
            dotColor = StatusGreenDot,
            modifier = modifier
        )
        ReservationStatus.RESERVEE -> StatusBadge(
            text = status.label,
            backgroundColor = StatusGoldBg,
            textColor = StatusGoldText,
            dotColor = StatusGoldDot,
            modifier = modifier
        )
        ReservationStatus.TERMINEE -> StatusBadge(
            text = status.label,
            backgroundColor = StatusGrayBg,
            textColor = StatusGrayText,
            dotColor = StatusGrayDot,
            modifier = modifier
        )
        ReservationStatus.ANNULEE -> StatusBadge(
            text = status.label,
            backgroundColor = StatusRedBg,
            textColor = StatusRedText,
            dotColor = StatusRedDot,
            modifier = modifier
        )
    }
}

@Composable
fun MaintenanceStepBadge(step: MaintenanceStep, modifier: Modifier = Modifier) {
    when (step) {
        MaintenanceStep.DIAGNOSTIC -> StatusBadge(
            text = step.label,
            backgroundColor = StatusGoldBg,
            textColor = StatusGoldText,
            dotColor = StatusGoldDot,
            modifier = modifier
        )
        MaintenanceStep.REPARATION -> StatusBadge(
            text = step.label,
            backgroundColor = StatusOrangeBg,
            textColor = StatusOrangeText,
            dotColor = StatusOrangeDot,
            modifier = modifier
        )
        MaintenanceStep.CONTROLE -> StatusBadge(
            text = step.label,
            backgroundColor = StatusGreenBg,
            textColor = StatusGreenText,
            dotColor = StatusGreenDot,
            modifier = modifier
        )
        MaintenanceStep.TERMINEE -> StatusBadge(
            text = step.label,
            backgroundColor = StatusGrayBg,
            textColor = StatusGrayText,
            dotColor = StatusGrayDot,
            modifier = modifier
        )
        MaintenanceStep.EN_ATTENTE -> StatusBadge(
            text = step.label,
            backgroundColor = StatusGoldBg,
            textColor = StatusGoldText,
            dotColor = StatusGoldDot,
            modifier = modifier
        )
    }
}
