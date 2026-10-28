// What the Android app is built on, in plain Kotlin (ADR 0011): the API client and its models,
// delta sync, the queue of reading positions, and the reader's page layout. A Kotlin
// Multiplatform module with only a JVM target for now (no iOS in CI until it is needed);
// Android consumes the JVM variant.
import org.jetbrains.kotlin.gradle.dsl.JvmTarget

plugins {
    alias(libs.plugins.kotlin.multiplatform)
    alias(libs.plugins.kotlin.serialization)
}

kotlin {
    jvm {
        compilerOptions {
            jvmTarget.set(JvmTarget.JVM_17)
        }
    }
    sourceSets {
        commonMain.dependencies {
            api(libs.bundles.ktor)
            api(libs.kotlinx.serialization.json)
            api(libs.kotlinx.coroutines.core)
        }
        jvmMain.dependencies {
            implementation(libs.ktor.client.okhttp)
        }
        commonTest.dependencies {
            implementation(kotlin("test"))
            implementation(libs.ktor.client.mock)
            implementation(libs.kotlinx.coroutines.test)
        }
    }
}

// The contract test checks the client against the server's OpenAPI document.
val openapi = rootProject.layout.projectDirectory.file("web/openapi.json")
tasks.named<Test>("jvmTest") {
    systemProperty("kodex.openapi", openapi.asFile.absolutePath)
    inputs.file(openapi).withPathSensitivity(PathSensitivity.RELATIVE).withPropertyName("openapi")
}
