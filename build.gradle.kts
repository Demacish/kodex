// Every plugin is declared here with `apply false`, so they share one classloader, and AGP's
// built-in Kotlin uses the catalog's Kotlin instead of its own default (as in Tandem).
plugins {
    alias(libs.plugins.android.application) apply false
    alias(libs.plugins.kotlin.multiplatform) apply false
    alias(libs.plugins.kotlin.compose) apply false
    alias(libs.plugins.kotlin.serialization) apply false
    alias(libs.plugins.ksp) apply false
    alias(libs.plugins.room3) apply false
}
