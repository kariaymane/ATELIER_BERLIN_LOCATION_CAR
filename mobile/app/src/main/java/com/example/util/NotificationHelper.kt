package com.example.util

import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.Context
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat

object NotificationHelper {
    private const val CHANNEL_ID = "soft_executive_channel"
    private const val CHANNEL_NAME = "Notifications ATELIER BERLIN LOCATION CAR"
    private const val CHANNEL_DESC = "Notifications en temps réel du système"

    fun createNotificationChannel(context: Context) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val importance = NotificationManager.IMPORTANCE_HIGH
            val channel = NotificationChannel(CHANNEL_ID, CHANNEL_NAME, importance).apply {
                description = CHANNEL_DESC
            }
            val notificationManager: NotificationManager =
                context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
            notificationManager.createNotificationChannel(channel)
        }
    }

    fun showNotification(context: Context, title: String, message: String, notificationId: Int = (title + message).hashCode()) {
        val builder = NotificationCompat.Builder(context, CHANNEL_ID)
            // Use Android's default icon for now, ideally replace with R.drawable.ic_notification
            .setSmallIcon(android.R.drawable.ic_dialog_info)
            .setContentTitle(title)
            .setContentText(message)
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .setAutoCancel(true)

        with(NotificationManagerCompat.from(context)) {
            // Suppress warning for POST_NOTIFICATIONS permission, assuming it's handled in UI or granted
            try {
                notify(notificationId, builder.build())
            } catch (e: SecurityException) {
                // Handle permission not granted
            }
        }
    }
}
