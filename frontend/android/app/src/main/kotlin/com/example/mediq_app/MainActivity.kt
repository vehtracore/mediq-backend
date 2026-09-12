package com.example.mediq_app

import android.app.NotificationChannel
import android.app.NotificationManager
import android.os.Build
import android.os.Bundle
import io.flutter.embedding.android.FlutterActivity

class MainActivity : FlutterActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        createNotificationChannels()
    }

    private fun createNotificationChannels() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
        val manager = getSystemService(NotificationManager::class.java)
        manager.createNotificationChannels(
            listOf(
                NotificationChannel(
                    "consultations",
                    "Consultations",
                    NotificationManager.IMPORTANCE_HIGH,
                ),
                NotificationChannel(
                    "general",
                    "General",
                    NotificationManager.IMPORTANCE_DEFAULT,
                ),
            ),
        )
    }
}
