package com.example

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.BackHandler
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.viewModels
import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.togetherWith
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Scaffold
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.Alignment
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.size
import androidx.compose.material3.Text
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.sp
import androidx.compose.ui.unit.dp
import androidx.compose.foundation.Image
import androidx.compose.ui.res.painterResource
import com.example.R
import com.example.ui.theme.ExecutiveGold
import com.example.data.api.ApiClient
import com.example.data.api.TokenManager
import com.example.data.local.AppDatabase
import com.example.data.repository.AuthRepository
import com.example.data.repository.FleetRepository
import com.example.data.sync.RealtimeSyncManager
import com.example.ui.components.ExecutiveBottomBar
import com.example.ui.screens.*
import com.example.ui.theme.ExecutiveBackground
import com.example.ui.theme.MyApplicationTheme
import com.example.ui.viewmodel.FleetViewModel
import com.example.ui.viewmodel.FleetViewModelFactory
import com.example.ui.viewmodel.Screen

class MainActivity : ComponentActivity() {

    private val viewModel: FleetViewModel by viewModels {
        val tokenManager = TokenManager(applicationContext)
        val apiClient = ApiClient(tokenManager)
        val database = AppDatabase.getDatabase(applicationContext)
        val authRepository = AuthRepository(apiClient, tokenManager)
        val fleetRepository = FleetRepository(apiClient, database, applicationContext)
        val realtimeSyncManager = RealtimeSyncManager(apiClient, tokenManager, fleetRepository)
        val themePreferences = com.example.data.local.ThemePreferences(applicationContext)
        val languagePreferences = com.example.data.local.LanguagePreferences(applicationContext)
        FleetViewModelFactory(authRepository, fleetRepository, realtimeSyncManager, themePreferences, languagePreferences)
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        com.example.util.NotificationHelper.createNotificationChannel(applicationContext)
        enableEdgeToEdge()
        setContent {
            val appTheme by viewModel.currentTheme.collectAsState()
            val appLanguage by viewModel.currentLanguage.collectAsState()

            val darkTheme = when (appTheme) {
                com.example.data.local.AppTheme.LIGHT -> false
                com.example.data.local.AppTheme.DARK -> true
                com.example.data.local.AppTheme.SYSTEM -> androidx.compose.foundation.isSystemInDarkTheme()
            }

            val layoutDirection = if (appLanguage == com.example.data.local.AppLanguage.AR) {
                androidx.compose.ui.unit.LayoutDirection.Rtl
            } else {
                androidx.compose.ui.unit.LayoutDirection.Ltr
            }

            androidx.compose.runtime.CompositionLocalProvider(
                androidx.compose.ui.platform.LocalLayoutDirection provides layoutDirection,
                com.example.ui.i18n.LocalAppLanguage provides appLanguage
            ) {
                MyApplicationTheme(darkTheme = darkTheme) {
                    AtelierBerlinApp(viewModel = viewModel)
                }
            }
        }
    }
}

@Composable
fun AtelierBerlinApp(viewModel: FleetViewModel) {
    val userSession by viewModel.userSession.collectAsState()
    val currentScreen by viewModel.currentScreen.collectAsState()
    val currentTab by viewModel.currentTab.collectAsState()

    // Handle back button
    BackHandler(enabled = currentScreen !is Screen.Dashboard && currentScreen !is Screen.Auth) {
        viewModel.navigateBack()
    }

    if (currentScreen is Screen.Splash) {
        SplashScaffold()
    } else if (userSession == null || currentScreen is Screen.Auth) {
        AuthScreen(
            viewModel = viewModel,
            onLoginSuccess = { /* Navigation handled in ViewModel */ }
        )
    } else {
        val showBottomBar = currentScreen is Screen.Dashboard ||
                currentScreen is Screen.Vehicles ||
                currentScreen is Screen.Reservations ||
                currentScreen is Screen.Maintenance ||
                currentScreen is Screen.Profile

        Scaffold(
            modifier = Modifier
                .fillMaxSize()
                .background(androidx.compose.material3.MaterialTheme.colorScheme.background),
            bottomBar = {
                if (showBottomBar) {
                    ExecutiveBottomBar(
                        currentTab = currentTab,
                        onTabSelected = { viewModel.selectTab(it) }
                    )
                }
            }
        ) { innerPadding ->
            Box(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(if (showBottomBar) innerPadding else androidx.compose.foundation.layout.PaddingValues())
                    .background(androidx.compose.material3.MaterialTheme.colorScheme.background)
            ) {
                AnimatedContent(
                    targetState = currentScreen,
                    transitionSpec = { fadeIn() togetherWith fadeOut() },
                    label = "ScreenTransition"
                ) { screen ->
                    when (screen) {
                        is Screen.Splash -> Box(
                            modifier = Modifier
                                .fillMaxSize()
                                .background(androidx.compose.material3.MaterialTheme.colorScheme.background),
                            contentAlignment = Alignment.Center
                        ) {
                            Column(horizontalAlignment = Alignment.CenterHorizontally) {
                                Image(
                                    painter = painterResource(id = R.drawable.logo_transparent_officiel),
                                    contentDescription = "ATELIER BERLIN LOCATION CAR Logo",
                                    contentScale = androidx.compose.ui.layout.ContentScale.Fit,
                                    modifier = Modifier.width(320.dp)
                                )
                                Spacer(modifier = Modifier.height(18.dp))
                                Text(
                                    text = "ATELIER BERLIN LOCATION CAR",
                                    fontSize = 18.sp,
                                    fontWeight = FontWeight.Bold,
                                    color = androidx.compose.ui.graphics.Color(0xFF1E4D38)
                                )
                                Spacer(modifier = Modifier.height(28.dp))
                                CircularProgressIndicator(
                                    color = ExecutiveGold,
                                    modifier = Modifier.size(30.dp),
                                    strokeWidth = 3.dp
                                )
                            }
                        }
                        is Screen.Dashboard -> DashboardScreen(viewModel = viewModel)
                        is Screen.Vehicles -> VehiclesScreen(viewModel = viewModel)
                        is Screen.VehicleDetail -> VehicleDetailScreen(
                            vehicleId = screen.vehicleId,
                            viewModel = viewModel
                        )
                        is Screen.Clients -> ClientsScreen(viewModel = viewModel)
                        is Screen.ClientDetail -> ClientDetailScreen(
                            clientId = screen.clientId,
                            viewModel = viewModel
                        )
                        is Screen.Reservations -> ReservationsScreen(viewModel = viewModel)
                        is Screen.ReservationDetail -> ReservationDetailScreen(
                            reservationId = screen.reservationId,
                            viewModel = viewModel
                        )
                        is Screen.Maintenance -> MaintenanceScreen(viewModel = viewModel)
                        is Screen.MaintenanceDetail -> MaintenanceDetailScreen(
                            maintenanceId = screen.maintenanceId,
                            viewModel = viewModel,
                            onBack = { viewModel.navigateBack() }
                        )
                        is Screen.Profile -> ProfileScreen(viewModel = viewModel)
                        is Screen.Auth -> AuthScreen(
                            viewModel = viewModel,
                            onLoginSuccess = { }
                        )
                    }
                }
            }
        }
    }
}

@Composable
private fun SplashScaffold() {
    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(ExecutiveBackground),
        contentAlignment = Alignment.Center
    ) {
        Column(horizontalAlignment = Alignment.CenterHorizontally) {
            Image(
                painter = painterResource(id = R.drawable.logo_transparent_officiel),
                contentDescription = "ATELIER BERLIN LOCATION CAR Logo",
                contentScale = androidx.compose.ui.layout.ContentScale.Fit,
                modifier = Modifier.width(320.dp)
            )
            Spacer(modifier = Modifier.height(18.dp))
            Text(
                text = "ATELIER BERLIN LOCATION CAR",
                fontSize = 18.sp,
                fontWeight = FontWeight.Bold,
                color = androidx.compose.ui.graphics.Color(0xFF1E4D38)
            )
            Spacer(modifier = Modifier.height(28.dp))
            CircularProgressIndicator(
                color = ExecutiveGold,
                modifier = Modifier.size(30.dp),
                strokeWidth = 3.dp
            )
        }
    }
}
