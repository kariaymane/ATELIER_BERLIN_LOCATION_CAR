package com.example.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.DirectionsCar
import androidx.compose.material.icons.filled.Email
import androidx.compose.material.icons.filled.Lock
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.Visibility
import androidx.compose.material.icons.filled.VisibilityOff
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.res.painterResource
import androidx.compose.foundation.Image
import com.example.R
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.platform.LocalFocusManager
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.example.ui.components.ErrorBanner
import com.example.ui.components.ExecutiveButton
import com.example.ui.theme.*
import com.example.ui.viewmodel.FleetViewModel

@Composable
fun AuthScreen(
    viewModel: FleetViewModel,
    onLoginSuccess: () -> Unit,
    modifier: Modifier = Modifier
) {
    var email by remember { mutableStateOf("") }
    var password by remember { mutableStateOf("") }
    var passwordVisible by remember { mutableStateOf(false) }
    var showServerConfig by remember { mutableStateOf(false) }
    var customBaseUrl by remember { mutableStateOf(viewModel.getBaseUrl()) }

    val isLoading by viewModel.isLoading.collectAsState()
    val errorMessage by viewModel.errorMessage.collectAsState()
    val focusManager = LocalFocusManager.current
    val scrollState = rememberScrollState()

    Box(
        modifier = modifier
            .fillMaxSize()
            .background(ExecutiveBackground)
            .statusBarsPadding()
            .navigationBarsPadding()
            .imePadding()
    ) {
        Column(
            modifier = Modifier
                .fillMaxSize()
                .verticalScroll(scrollState)
                .padding(horizontal = 24.dp, vertical = 24.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.Center
        ) {
            Spacer(modifier = Modifier.height(24.dp))

            // App Logo (200dp fixed width, height scales automatically)
            Image(
                painter = painterResource(id = R.drawable.logo_transparent_officiel),
                contentDescription = "ATELIER BERLIN LOCATION CAR Logo",
                contentScale = ContentScale.Fit,
                modifier = Modifier
                    .width(260.dp)
                    .wrapContentHeight()
            )

            Spacer(modifier = Modifier.height(28.dp))

            // ATELIER BERLIN LOCATION CAR Title matching Pistache theme
            Text(
                text = "ATELIER BERLIN LOCATION CAR",
                fontSize = 24.sp,
                fontWeight = FontWeight.Bold,
                fontFamily = FontFamily.Serif,
                color = ExecutiveTextPrimary,
                textAlign = TextAlign.Center
            )

            Spacer(modifier = Modifier.height(6.dp))

            Text(
                text = "Gestion de Flotte Automobile & Opérations",
                fontSize = 14.sp,
                color = ExecutiveTextSecondary,
                textAlign = TextAlign.Center
            )

            Spacer(modifier = Modifier.height(32.dp))

            // Login Card
            Surface(
                modifier = Modifier
                    .fillMaxWidth()
                    .shadow(elevation = 2.dp, shape = RoundedCornerShape(20.dp)),
                shape = RoundedCornerShape(20.dp),
                color = ExecutiveSurface,
                border = androidx.compose.foundation.BorderStroke(1.dp, ExecutiveBorder)
            ) {
                Column(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(24.dp)
                ) {
                    Text(
                        text = "Connexion",
                        fontSize = 20.sp,
                        fontWeight = FontWeight.Bold,
                        fontFamily = FontFamily.Serif,
                        color = ExecutiveTextPrimary
                    )

                    Spacer(modifier = Modifier.height(6.dp))

                    Text(
                        text = "Accédez à votre espace opérationnel",
                        fontSize = 13.sp,
                        color = ExecutiveTextSecondary
                    )

                    Spacer(modifier = Modifier.height(20.dp))

                    if (errorMessage != null) {
                        ErrorBanner(
                            message = errorMessage!!,
                            onRetry = { viewModel.clearMessages() },
                            modifier = Modifier.padding(bottom = 16.dp)
                        )
                    }

                    // Email field
                    OutlinedTextField(
                        value = email,
                        onValueChange = { email = it },
                        enabled = !isLoading,
                        label = { Text("Email", color = ExecutiveTextSecondary) },
                        placeholder = { Text("email@example.com", color = ExecutiveTextTertiary) },
                        leadingIcon = {
                            Icon(
                                imageVector = Icons.Default.Email,
                                contentDescription = null,
                                tint = ExecutiveTextSecondary
                            )
                        },
                        singleLine = true,
                        colors = OutlinedTextFieldDefaults.colors(
                            focusedBorderColor = ExecutivePrimaryGreen,
                            unfocusedBorderColor = ExecutiveBorder,
                            focusedLabelColor = ExecutivePrimaryGreen,
                            unfocusedLabelColor = ExecutiveTextSecondary,
                            focusedTextColor = ExecutiveTextPrimary,
                            unfocusedTextColor = ExecutiveTextPrimary,
                            disabledTextColor = ExecutiveTextSecondary,
                            disabledBorderColor = ExecutiveBorder.copy(alpha = 0.5f)
                        ),
                        shape = RoundedCornerShape(12.dp),
                        keyboardOptions = KeyboardOptions(
                            keyboardType = KeyboardType.Email,
                            imeAction = ImeAction.Next
                        ),
                        modifier = Modifier.fillMaxWidth()
                    )

                    Spacer(modifier = Modifier.height(16.dp))

                    // Password field
                    OutlinedTextField(
                        value = password,
                        onValueChange = { password = it },
                        enabled = !isLoading,
                        label = { Text("Mot de passe", color = ExecutiveTextSecondary) },
                        placeholder = { Text("••••••••", color = ExecutiveTextTertiary) },
                        leadingIcon = {
                            Icon(
                                imageVector = Icons.Default.Lock,
                                contentDescription = null,
                                tint = ExecutiveTextSecondary
                            )
                        },
                        trailingIcon = {
                            IconButton(onClick = { passwordVisible = !passwordVisible }, enabled = !isLoading) {
                                Icon(
                                    imageVector = if (passwordVisible) Icons.Default.Visibility else Icons.Default.VisibilityOff,
                                    contentDescription = if (passwordVisible) "Masquer" else "Afficher",
                                    tint = ExecutiveTextSecondary
                                )
                            }
                        },
                        visualTransformation = if (passwordVisible) VisualTransformation.None else PasswordVisualTransformation(),
                        singleLine = true,
                        colors = OutlinedTextFieldDefaults.colors(
                            focusedBorderColor = ExecutivePrimaryGreen,
                            unfocusedBorderColor = ExecutiveBorder,
                            focusedLabelColor = ExecutivePrimaryGreen,
                            unfocusedLabelColor = ExecutiveTextSecondary,
                            focusedTextColor = ExecutiveTextPrimary,
                            unfocusedTextColor = ExecutiveTextPrimary,
                            disabledTextColor = ExecutiveTextSecondary,
                            disabledBorderColor = ExecutiveBorder.copy(alpha = 0.5f)
                        ),
                        shape = RoundedCornerShape(12.dp),
                        keyboardOptions = KeyboardOptions(
                            keyboardType = KeyboardType.Password,
                            imeAction = ImeAction.Done
                        ),
                        keyboardActions = KeyboardActions(
                            onDone = {
                                focusManager.clearFocus()
                                if (email.isNotBlank() && password.isNotBlank()) {
                                    viewModel.login(email, password) { success ->
                                        if (success) onLoginSuccess()
                                    }
                                }
                            }
                        ),
                        modifier = Modifier.fillMaxWidth()
                    )

                    Spacer(modifier = Modifier.height(24.dp))

                    // Se connecter Button
                    ExecutiveButton(
                        text = "Se connecter",
                        isLoading = isLoading,
                        onClick = {
                            focusManager.clearFocus()
                            if (email.isNotBlank() && password.isNotBlank()) {
                                viewModel.login(email, password) { success ->
                                    if (success) onLoginSuccess()
                                }
                            }
                        },
                        modifier = Modifier.fillMaxWidth()
                    )
                }
            }

            Spacer(modifier = Modifier.height(24.dp))

        }
    }
}
