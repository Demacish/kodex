// The Android app (androidApp/) and the Kotlin module it is built on (shared/).
// The backend and the web client build on their own (backend/, web/).
pluginManagement {
    repositories {
        google()
        mavenCentral()
        gradlePluginPortal()
    }
}

dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {
        google()
        mavenCentral()
    }
}

rootProject.name = "kodex"

include(":shared")
include(":androidApp")
