// The Android app (androidApp/) and the Kotlin module it is built on (shared/).
// The backend and the web client build on their own (backend/, web/).
pluginManagement {
    repositories {
        google()
        // Maven Central through Google's mirror first: Maven Central answers GitHub's runners with 429
        // for large files (Robolectric's native runtime, 159 MB) when many ask at once; it stays as the fallback.
        maven("https://maven-central.storage-download.googleapis.com/maven2/")
        mavenCentral()
        gradlePluginPortal()
    }
}

dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {
        google()
        // Maven Central through Google's mirror first: Maven Central answers GitHub's runners with 429
        // for large files (Robolectric's native runtime, 159 MB) when many ask at once; it stays as the fallback.
        maven("https://maven-central.storage-download.googleapis.com/maven2/")
        mavenCentral()
    }
}

rootProject.name = "kodex"

include(":shared")
include(":androidApp")
