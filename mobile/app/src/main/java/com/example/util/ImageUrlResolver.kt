package com.example.util

import android.util.Log

object ImageUrlResolver {
    fun resolve(raw: String?, rootUrl: String, version: Int = 1): String {
        val s = raw?.trim()?.ifEmpty { null } ?: return ""
        
        var finalUrl = s
        if (!s.startsWith("http://") && !s.startsWith("https://")) {
            val cleanRoot = rootUrl.trimEnd('/').removeSuffix("/api/v1").removeSuffix("/api").removeSuffix("/v1")
            var path = s.trimStart('/')
            
            if (path.startsWith("uploads/")) {
                path = "static/$path"
            } else if (!path.startsWith("static/uploads/")) {
                if (path.startsWith("vehicles/")) {
                    path = "static/uploads/$path"
                } else {
                    path = "static/uploads/vehicles/$path"
                }
            }
            
            path = path.replace(Regex("/+"), "/")
            finalUrl = "$cleanRoot/$path"
        }
        
        val res = if (finalUrl.contains("?")) "$finalUrl&v=$version" else "$finalUrl?v=$version"
        Log.d("IMAGE_TRACE", "IMAGE_API_URL=" + raw + " -> " + res)
        return res
    }
}
