// The Kodex Android app (phase 5). Built only in GitHub Actions (.github/workflows/android.yml);
// the plain-Kotlin parts it shares (API client, sync, position queue, page layout) are in :shared.
import androidx.room3.gradle.RoomExtension

plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.compose)
    alias(libs.plugins.kotlin.serialization)
    alias(libs.plugins.ksp)
    alias(libs.plugins.room3)
}

// Release signing comes only from the environment (the release workflow decodes the keystore
// from a secret); without KODEX_KEYSTORE_PATH the release APK is built unsigned.
val signing = listOf("KODEX_KEYSTORE_PATH", "KODEX_KEYSTORE_PASSWORD", "KODEX_KEY_ALIAS", "KODEX_KEY_PASSWORD")
    .associateWith { providers.environmentVariable(it).orNull.orEmpty() }
val signed = signing.getValue("KODEX_KEYSTORE_PATH").isNotEmpty()

android {
    namespace = "app.kodex"
    compileSdk = libs.versions.compileSdk.get().toInt()

    defaultConfig {
        applicationId = "app.kodex"
        minSdk = libs.versions.minSdk.get().toInt()
        targetSdk = libs.versions.targetSdk.get().toInt()
        // major * 10000 + minor * 100 + patch, so every release counts up.
        versionCode = 20100
        versionName = "2.1.0"
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
        // Readium's media modules (reading aloud) use java.time and friends below API 33.
        isCoreLibraryDesugaringEnabled = true
    }

    buildFeatures {
        compose = true
        buildConfig = true
    }

    androidResources {
        generateLocaleConfig = true
        localeFilters += listOf("en", "sv")
    }

    signingConfigs {
        if (signed) {
            create("release") {
                storeFile = file(signing.getValue("KODEX_KEYSTORE_PATH"))
                storePassword = signing.getValue("KODEX_KEYSTORE_PASSWORD")
                keyAlias = signing.getValue("KODEX_KEY_ALIAS")
                keyPassword = signing.getValue("KODEX_KEY_PASSWORD")
                storeType = "pkcs12"
            }
        }
    }

    buildTypes {
        getByName("debug") {
            applicationIdSuffix = ".dev"
            versionNameSuffix = "-debug"
        }
        getByName("release") {
            if (signed) signingConfig = signingConfigs.getByName("release")
            isMinifyEnabled = true
            isShrinkResources = true
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
        }
    }

    testOptions {
        unitTests.isIncludeAndroidResources = true
    }

    packaging {
        resources.excludes += listOf("META-INF/INDEX.LIST", "META-INF/*.kotlin_module", "META-INF/io.netty.versions.properties")
    }

    lint {
        abortOnError = true
        warningsAsErrors = false
        error += listOf("MissingTranslation", "ExtraTranslation", "HardcodedText")
        // Readium and androidx.pdf are on the versions ADR 0012 chose; lint's "newer version
        // available" isn't a reason to fail.
        disable += listOf("GradleDependency", "NewerVersionAvailable", "AndroidGradlePluginVersion")
    }
}

extensions.configure<RoomExtension> {
    schemaDirectory(layout.projectDirectory.dir("schemas"))
}

tasks.withType<Test>().configureEach {
    maxHeapSize = "1536m"
    // Robolectric with SDK 36 on JDK 21 (as in Tandem).
    jvmArgs("--add-opens=java.base/jdk.internal.access=ALL-UNNAMED", "--add-opens=java.base/java.io=ALL-UNNAMED")
}

dependencies {
    implementation(project(":shared"))
    coreLibraryDesugaring(libs.desugar.jdk.libs)

    implementation(libs.androidx.core.ktx)
    implementation(libs.androidx.activity.compose)
    implementation(libs.androidx.fragment.compose)
    implementation(libs.androidx.lifecycle.runtime.compose)
    implementation(libs.androidx.lifecycle.viewmodel.compose)
    implementation(libs.androidx.lifecycle.process)
    implementation(libs.androidx.browser)
    implementation(libs.androidx.glance.appwidget)

    implementation(platform(libs.androidx.compose.bom))
    implementation(libs.bundles.compose.ui)
    implementation(libs.androidx.compose.material3.adaptive.navigation3)
    implementation(libs.bundles.navigation3)
    debugImplementation(libs.androidx.compose.ui.tooling)

    implementation(libs.androidx.room3.runtime)
    ksp(libs.androidx.room3.compiler)
    implementation(libs.androidx.datastore.preferences)
    implementation(libs.androidx.work.runtime)

    implementation(platform(libs.koin.bom))
    implementation(libs.koin.android)
    implementation(libs.koin.androidx.compose)

    implementation(libs.ktor.client.okhttp)
    implementation(libs.kotlinx.coroutines.android)
    implementation(libs.coil.compose)
    implementation(libs.coil.network.ktor)

    implementation(libs.readium.shared)
    implementation(libs.readium.streamer)
    implementation(libs.readium.navigator)
    implementation(libs.readium.navigator.media.tts)
    implementation(libs.androidx.pdf.compose)
    implementation(libs.androidx.pdf.document.service)

    testImplementation(libs.junit4)
    testImplementation(libs.robolectric)
    testImplementation(libs.kotlinx.coroutines.test)
    testImplementation(libs.androidx.test.core)
    testImplementation(libs.androidx.test.ext.junit)
    testImplementation(libs.androidx.room3.testing)
    testImplementation(libs.androidx.work.testing)
    testImplementation(libs.ktor.client.mock)

    androidTestImplementation(platform(libs.androidx.compose.bom))
    androidTestImplementation(libs.androidx.compose.ui.test.junit4)
    debugImplementation(libs.androidx.compose.ui.test.manifest)
    androidTestImplementation(libs.androidx.test.core)
    androidTestImplementation(libs.androidx.test.ext.junit)
    androidTestImplementation(libs.androidx.test.runner)
    androidTestImplementation(libs.androidx.work.testing)
    androidTestImplementation(libs.okhttp.mockwebserver)
    androidTestImplementation(libs.kotlinx.coroutines.test)
}
