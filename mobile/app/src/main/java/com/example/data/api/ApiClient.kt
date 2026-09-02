package com.example.data.api

import android.util.Log
import com.example.BuildConfig
import com.squareup.moshi.Moshi
import com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory
import kotlinx.coroutines.runBlocking
import okhttp3.Authenticator
import okhttp3.Interceptor
import okhttp3.OkHttpClient
import okhttp3.Route
import okhttp3.Response
import okhttp3.logging.HttpLoggingInterceptor
import retrofit2.Retrofit
import retrofit2.converter.moshi.MoshiConverterFactory
import java.util.concurrent.TimeUnit

class AuthInterceptor(private val tokenManager: TokenManager) : Interceptor {
    override fun intercept(chain: Interceptor.Chain): Response {
        val requestBuilder = chain.request().newBuilder()
        val token = tokenManager.getToken()
        if (!token.isNullOrBlank()) {
            requestBuilder.addHeader("Authorization", "Bearer $token")
        }
        requestBuilder.addHeader("Accept", "application/json")
        requestBuilder.addHeader("Content-Type", "application/json")
        requestBuilder.addHeader("X-Client-Origin", "Mobile")
        return chain.proceed(requestBuilder.build())
    }
}

class TokenAuthenticator(
    private val tokenManager: TokenManager,
    private val apiServiceProvider: () -> ApiService
) : Authenticator {
    override fun authenticate(route: Route?, response: Response): okhttp3.Request? {
        Log.w("SYNC", "[AUTH] 401 Unauthorized received for ${response.request.url}")
        val refreshToken = tokenManager.getRefreshToken()
        if (refreshToken.isNullOrBlank()) {
            Log.e("SYNC", "[AUTH] No refresh token available in TokenManager! Cannot refresh. Clearing session.")
            tokenManager.clearTokens()
            return null
        }

        return synchronized(this) {
            val currentToken = tokenManager.getToken()
            if (response.request.header("Authorization") != "Bearer $currentToken") {
                Log.i("SYNC", "[AUTH] Token was already refreshed by another concurrent request, retrying with new token.")
                return response.request.newBuilder()
                    .header("Authorization", "Bearer ${tokenManager.getToken()}")
                    .build()
            }

            Log.i("SYNC", "[AUTH] Requesting new access token via /api/v1/auth/refresh...")
            val apiService = apiServiceProvider()
            var newAccessToken: String? = null

            runBlocking {
                try {
                    val refreshResponse = apiService.refreshToken(RefreshRequestDto(refreshToken))
                    Log.i("SYNC", "[AUTH] Refresh response code = ${refreshResponse.code()}")
                    if (refreshResponse.isSuccessful && refreshResponse.body() != null) {
                        newAccessToken = refreshResponse.body()!!.accessToken
                        val newRefreshToken = refreshResponse.body()!!.refreshToken
                        tokenManager.saveToken(newAccessToken!!)
                        tokenManager.saveRefreshToken(newRefreshToken)
                        Log.i("SYNC", "[AUTH] Successfully refreshed access token!")
                    } else {
                        Log.e("SYNC", "[AUTH] Refresh token rejected (HTTP ${refreshResponse.code()}), clearing tokens.")
                        tokenManager.clearTokens()
                    }
                } catch (e: Exception) {
                    Log.e("SYNC", "[AUTH] Refresh token network error: ${e.message}. Retaining tokens for offline mode.", e)
                }
            }

            newAccessToken?.let {
                response.request.newBuilder()
                    .header("Authorization", "Bearer $it")
                    .build()
            }
        }
    }
}

class ApiClient(private val tokenManager: TokenManager) {

    private val moshi: Moshi = Moshi.Builder()
        .add(KotlinJsonAdapterFactory())
        .build()

    // SECURITY: HTTP logging is line-level only (method + URL + status + timing)
    // and is disabled entirely in release builds. Even so, sensitive headers are
    // redacted so that a future bump to HEADERS/BODY can never leak a bearer
    // token or a Set-Cookie. Request BODIES (which include the /auth/login
    // password) are never logged at BASIC level.
    private val loggingInterceptor = HttpLoggingInterceptor().apply {
        level = if (BuildConfig.DEBUG) HttpLoggingInterceptor.Level.BASIC
                else HttpLoggingInterceptor.Level.NONE
        redactHeader("Authorization")
        redactHeader("Cookie")
        redactHeader("Set-Cookie")
    }

    private val okHttpClient: OkHttpClient = OkHttpClient.Builder()
        .addInterceptor(AuthInterceptor(tokenManager))
        .authenticator(TokenAuthenticator(tokenManager) { getService() })
        .addInterceptor(loggingInterceptor)
        .connectTimeout(15, TimeUnit.SECONDS)
        .readTimeout(20, TimeUnit.SECONDS)
        .writeTimeout(20, TimeUnit.SECONDS)
        .retryOnConnectionFailure(true)
        .build()

    private var currentBaseUrl: String = tokenManager.getBaseUrl()
    private var currentService: ApiService = createService(currentBaseUrl)

    private fun createService(baseUrl: String): ApiService {
        Log.i("API", "[API] Base URL = $baseUrl")
        return Retrofit.Builder()
            .baseUrl(baseUrl)
            .client(okHttpClient)
            .addConverterFactory(MoshiConverterFactory.create(moshi))
            .build()
            .create(ApiService::class.java)
    }

    fun getBaseUrl(): String = tokenManager.getBaseUrl()
    fun getRootUrl(): String = tokenManager.getRootUrl()

    fun getService(): ApiService {
        val configuredBaseUrl = tokenManager.getBaseUrl()
        if (configuredBaseUrl != currentBaseUrl) {
            currentBaseUrl = configuredBaseUrl
            currentService = createService(currentBaseUrl)
        }
        return currentService
    }
}
