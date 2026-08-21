package com.example.data.sync

import android.util.Log
import com.example.data.api.ApiClient
import com.example.data.api.TokenManager
import com.example.data.api.WebSocketEventDto
import com.example.data.repository.FleetRepository
import com.squareup.moshi.Moshi
import com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import okhttp3.*
import java.util.concurrent.TimeUnit

enum class RealtimeConnectionState {
    DISCONNECTED,
    CONNECTING,
    CONNECTED,
    RECONNECTING
}

class RealtimeSyncManager(
    private val apiClient: ApiClient,
    private val tokenManager: TokenManager,
    private val fleetRepository: FleetRepository
) {
    private val tag = "RealtimeSyncManager"

    private val moshi: Moshi = Moshi.Builder()
        .add(KotlinJsonAdapterFactory())
        .build()
    private val eventAdapter = moshi.adapter(WebSocketEventDto::class.java)

    private val okHttpClient: OkHttpClient = OkHttpClient.Builder()
        .connectTimeout(10, TimeUnit.SECONDS)
        .readTimeout(0, TimeUnit.MILLISECONDS) // Keep-alive for WebSocket
        .writeTimeout(10, TimeUnit.SECONDS)
        .pingInterval(15, TimeUnit.SECONDS)
        .retryOnConnectionFailure(true)
        .build()

    private var webSocket: WebSocket? = null
    private val scope = CoroutineScope(Dispatchers.IO + SupervisorJob())

    private val _connectionState = MutableStateFlow(RealtimeConnectionState.DISCONNECTED)
    val connectionState: StateFlow<RealtimeConnectionState> = _connectionState.asStateFlow()

    private var isRunning = false
    private var reconnectJob: Job? = null
    private var fallbackPollJob: Job? = null
    private var pingJob: Job? = null
    private var reconnectDelayMs = 2000L
    private val maxReconnectDelayMs = 30000L

    fun start() {
        if (isRunning) return
        isRunning = true
        Log.i(tag, "Starting Realtime Sync Engine...")
        connect()
    }

    fun stop() {
        isRunning = false
        reconnectJob?.cancel()
        fallbackPollJob?.cancel()
        pingJob?.cancel()
        webSocket?.close(1000, "Client stopped")
        webSocket = null
        _connectionState.value = RealtimeConnectionState.DISCONNECTED
        fleetRepository.updateRealtimeConnection(false)
        Log.i(tag, "Realtime Sync Engine stopped")
    }

    @Synchronized
    private fun connect() {
        if (!isRunning) return

        val rootUrl = tokenManager.getRootUrl()
        val wsUrl = rootUrl.replace("http://", "ws://").replace("https://", "wss://") + "/api/v1/events/ws"
        val token = tokenManager.getToken()

        Log.d(tag, "Connecting to WebSocket: $wsUrl")
        _connectionState.value = if (_connectionState.value == RealtimeConnectionState.DISCONNECTED) {
            RealtimeConnectionState.CONNECTING
        } else {
            RealtimeConnectionState.RECONNECTING
        }

        val requestBuilder = Request.Builder().url(wsUrl)
        if (!token.isNullOrBlank()) {
            requestBuilder.addHeader("Authorization", "Bearer $token")
        }
        requestBuilder.addHeader("X-Client-Origin", "Mobile")

        webSocket = okHttpClient.newWebSocket(requestBuilder.build(), object : WebSocketListener() {
            override fun onOpen(ws: WebSocket, response: Response) {
                Log.i(tag, "WebSocket CONNECTED to $wsUrl")
                _connectionState.value = RealtimeConnectionState.CONNECTED
                reconnectDelayMs = 2000L
                fallbackPollJob?.cancel()
                fleetRepository.updateRealtimeConnection(true)

                // When reconnected, refresh all data to catch up on any changes missed during disconnect
                scope.launch {
                    try {
                        fleetRepository.refreshAll()
                    } catch (e: Exception) {
                        Log.w(tag, "Post-reconnect catch-up sync warning: ${e.message}")
                    }
                }

                startHeartbeat(ws)
            }

            override fun onMessage(ws: WebSocket, text: String) {
                Log.d(tag, "WebSocket Message received: $text")
                scope.launch {
                    try {
                        val event = eventAdapter.fromJson(text)
                        if (event != null) {
                            if (event.type == "PONG" || event.eventType == "CONNECTED") {
                                Log.d(tag, "Handshake/Heartbeat event: ${event.eventType ?: event.type}")
                            } else {
                                Log.i(tag, "Authoritative Event received: ${event.eventType ?: event.type} for ${event.entityType ?: event.entity} (ID: ${event.entityId})")
                                fleetRepository.handleRealtimeEvent(event)
                            }
                        }
                    } catch (e: Exception) {
                        Log.e(tag, "Error parsing / processing WebSocket event: ${e.message}", e)
                    }
                }
            }

            override fun onClosing(ws: WebSocket, code: Int, reason: String) {
                Log.w(tag, "WebSocket closing (code $code): $reason")
                ws.close(1000, null)
            }

            override fun onClosed(ws: WebSocket, code: Int, reason: String) {
                Log.w(tag, "WebSocket closed (code $code): $reason")
                handleDisconnect()
            }

            override fun onFailure(ws: WebSocket, t: Throwable, response: Response?) {
                Log.e(tag, "WebSocket failure: ${t.message}")
                handleDisconnect()
            }
        })
    }

    private fun startHeartbeat(ws: WebSocket) {
        pingJob?.cancel()
        pingJob = scope.launch {
            while (isActive && isRunning && _connectionState.value == RealtimeConnectionState.CONNECTED) {
                delay(15000)
                try {
                    ws.send("{\"type\":\"PING\"}")
                } catch (e: Exception) {
                    Log.w(tag, "Failed to send ping: ${e.message}")
                    break
                }
            }
        }
    }

    private fun handleDisconnect() {
        pingJob?.cancel()
        _connectionState.value = RealtimeConnectionState.DISCONNECTED
        fleetRepository.updateRealtimeConnection(false)

        if (!isRunning) return

        // Start fallback polling while disconnected
        startFallbackPolling()

        // Schedule reconnection with exponential backoff
        reconnectJob?.cancel()
        reconnectJob = scope.launch {
            Log.i(tag, "Reconnecting in ${reconnectDelayMs / 1000}s...")
            delay(reconnectDelayMs)
            reconnectDelayMs = (reconnectDelayMs * 1.5).toLong().coerceAtMost(maxReconnectDelayMs)
            connect()
        }
    }

    private fun startFallbackPolling() {
        if (fallbackPollJob?.isActive == true) return
        Log.i(tag, "Starting fallback periodic polling sync (every 20s)...")
        fallbackPollJob = scope.launch {
            while (isActive && isRunning && _connectionState.value != RealtimeConnectionState.CONNECTED) {
                delay(20000)
                try {
                    Log.d(tag, "Executing fallback periodic pull sync...")
                    fleetRepository.refreshAll()
                } catch (e: Exception) {
                    Log.w(tag, "Fallback polling sync warning: ${e.message}")
                }
            }
        }
    }
}
