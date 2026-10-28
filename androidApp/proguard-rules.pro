# Kodex release build (R8). Libraries bring their own rules (kotlinx.serialization, Ktor,
# Readium, androidx); these are only for what they don't cover.

# Ktor and OkHttp refer to JVM classes that Android doesn't have.
-dontwarn java.lang.management.**
-dontwarn org.slf4j.**
-dontwarn org.conscrypt.**
-dontwarn org.bouncycastle.**
-dontwarn org.openjsse.**

# Navigation 3 saves the back stack with the keys' serializers.
-keep class app.kodex.ui.*Key { *; }
-keep class app.kodex.ui.*Key$Companion { *; }
