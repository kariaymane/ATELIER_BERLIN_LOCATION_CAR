package com.example.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.CloudOff
import androidx.compose.material.icons.filled.Storage
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.example.data.model.SyncStatus
import com.example.ui.theme.StatusGrayBg
import com.example.ui.theme.StatusGrayText
import com.example.ui.theme.StatusOrangeBg
import com.example.ui.theme.StatusOrangeText

/**
 * Slim, non-fatal banner shown when the screen is displaying LOCAL (Room) data
 * that is not currently being kept live. It never replaces content — the cached
 * rows stay visible beneath it — and it always makes clear the data is offline
 * / stale (never presenting stale data as live).
 *
 *   SERVER_DB_UNAVAILABLE → "server reachable, its database is down" (orange, transient)
 *   otherwise (SYNC_ERROR / DISCONNECTED) → "offline" (gray)
 *
 * Renders nothing unless [syncStatus.isShowingStaleData] and there is something
 * cached to annotate ([hasCachedData]).
 */
@Composable
fun OfflineBanner(
    syncStatus: SyncStatus,
    hasCachedData: Boolean,
    onRetry: () -> Unit,
    modifier: Modifier = Modifier,
) {
    if (!syncStatus.isShowingStaleData || !hasCachedData) return

    val dbDown = syncStatus.isServerDatabaseDown
    val bg = if (dbDown) StatusOrangeBg else StatusGrayBg
    val fg = if (dbDown) StatusOrangeText else StatusGrayText
    val icon = if (dbDown) Icons.Filled.Storage else Icons.Filled.CloudOff

    val headline = if (dbDown) {
        "Base de données du serveur indisponible"
    } else {
        "Hors ligne"
    }
    val detail = buildString {
        append(
            if (dbDown) {
                "Serveur accessible, mais sa base de données ne répond pas. "
            } else {
                "Impossible de joindre le serveur. "
            }
        )
        append("Données locales affichées")
        syncStatus.lastSyncTime?.takeIf { it.isNotBlank() }?.let {
            append(" · dernière synchronisation à $it")
        }
        append(".")
    }

    Row(
        modifier = modifier
            .fillMaxWidth()
            .padding(horizontal = 16.dp, vertical = 6.dp)
            .clip(RoundedCornerShape(10.dp))
            .background(bg)
            .padding(start = 12.dp, top = 8.dp, bottom = 8.dp, end = 4.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        Icon(icon, contentDescription = null, tint = fg)
        Column(modifier = Modifier.weight(1f)) {
            Text(headline, color = fg, fontWeight = FontWeight.SemiBold, fontSize = 13.sp)
            Text(detail, color = fg, fontSize = 12.sp)
        }
        TextButton(onClick = onRetry) {
            Text("Réessayer", color = fg, fontWeight = FontWeight.SemiBold, fontSize = 13.sp)
        }
    }
}
