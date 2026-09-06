import java.net.URI

plugins {
  alias(libs.plugins.android.application)
  alias(libs.plugins.kotlin.compose)
  alias(libs.plugins.google.devtools.ksp)
}

// The API address is public configuration, never a credential.
val configuredApiUrl = providers.gradleProperty("apiBaseUrl")
  .orElse(providers.environmentVariable("API_BASE_URL"))
  .orElse("https://api.example.invalid/")
  .map { it.trim().trimEnd('/') + "/" }
val apiUri = URI(configuredApiUrl.get())
require(
  apiUri.scheme == "https" && apiUri.host != null &&
    apiUri.rawUserInfo == null && apiUri.rawQuery == null &&
    apiUri.rawFragment == null && apiUri.path == "/"
) { "API_BASE_URL must be an HTTPS origin without credentials, a path, or a query." }

val keystorePath = providers.environmentVariable("KEYSTORE_PATH")
val storePasswordValue = providers.environmentVariable("STORE_PASSWORD")
val keyAliasValue = providers.environmentVariable("KEY_ALIAS")
val keyPasswordValue = providers.environmentVariable("KEY_PASSWORD")

android {
  // Preserve the application ID for compatibility with existing installations.
  namespace = "com.example"
  compileSdk { version = release(36) { minorApiLevel = 1 } }

  defaultConfig {
    applicationId = "com.example"
    minSdk = 24
    targetSdk = 36
    versionCode = 1
    versionName = "1.0"
    testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
    buildConfigField("String", "API_BASE_URL", "\"${configuredApiUrl.get()}\"")
  }

  signingConfigs {
    create("release") {
      keystorePath.orNull?.let { storeFile = file(it) }
      storePassword = storePasswordValue.orNull
      keyAlias = keyAliasValue.orNull
      keyPassword = keyPasswordValue.orNull
    }
  }

  buildTypes {
    release {
      isCrunchPngs = false
      isMinifyEnabled = false
      proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
      signingConfig = signingConfigs.getByName("release")
    }
    // Debug builds use the standard Android debug keystore, never release keys.
  }
  compileOptions {
    sourceCompatibility = JavaVersion.VERSION_11
    targetCompatibility = JavaVersion.VERSION_11
  }
  buildFeatures {
    compose = true
    buildConfig = true
  }
  testOptions { unitTests { isIncludeAndroidResources = true } }
  dependenciesInfo {
    includeInApk = false
    includeInBundle = true
  }
}

val validateReleaseConfiguration by tasks.registering {
  doLast {
    check(!configuredApiUrl.get().contains("example.invalid")) {
      "Set API_BASE_URL or -PapiBaseUrl for release builds."
    }
    check(listOf(keystorePath, storePasswordValue, keyAliasValue, keyPasswordValue)
      .all { !it.orNull.isNullOrBlank() }) {
      "Release signing requires KEYSTORE_PATH, STORE_PASSWORD, KEY_ALIAS, and KEY_PASSWORD."
    }
  }
}
tasks.matching { it.name == "preReleaseBuild" }.configureEach {
  dependsOn(validateReleaseConfiguration)
}

dependencies {
  implementation(platform(libs.androidx.compose.bom))
  implementation(libs.androidx.activity.compose)
  implementation(libs.androidx.compose.material.icons.core)
  implementation(libs.androidx.compose.material.icons.extended)
  implementation(libs.androidx.compose.material3)
  implementation(libs.androidx.compose.ui)
  implementation(libs.androidx.compose.ui.graphics)
  implementation(libs.androidx.compose.ui.tooling.preview)
  implementation(libs.androidx.core.ktx)
  implementation(libs.androidx.lifecycle.runtime.compose)
  implementation(libs.androidx.lifecycle.runtime.ktx)
  implementation(libs.androidx.lifecycle.viewmodel.compose)
  implementation(libs.androidx.room.ktx)
  implementation(libs.androidx.room.runtime)
  implementation(libs.coil.compose)
  implementation(libs.converter.moshi)
  implementation(libs.kotlinx.coroutines.android)
  implementation(libs.kotlinx.coroutines.core)
  implementation(libs.logging.interceptor)
  implementation(libs.moshi.kotlin)
  implementation(libs.okhttp)
  implementation(libs.retrofit)
  testImplementation(libs.androidx.compose.ui.test.junit4)
  testImplementation(libs.androidx.core)
  testImplementation(libs.androidx.junit)
  testImplementation(libs.junit)
  testImplementation(libs.kotlinx.coroutines.test)
  testImplementation(libs.mockwebserver)
  testImplementation(libs.robolectric)
  androidTestImplementation(platform(libs.androidx.compose.bom))
  androidTestImplementation(libs.androidx.compose.ui.test.junit4)
  androidTestImplementation(libs.androidx.espresso.core)
  androidTestImplementation(libs.androidx.junit)
  androidTestImplementation(libs.androidx.runner)
  debugImplementation(libs.androidx.compose.ui.test.manifest)
  debugImplementation(libs.androidx.compose.ui.tooling)
  "ksp"(libs.androidx.room.compiler)
  "ksp"(libs.moshi.kotlin.codegen)
}
