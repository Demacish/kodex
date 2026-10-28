package app.kodex.shared.auth

import java.security.MessageDigest
import java.security.SecureRandom
import java.util.Base64

/**
 * Logging in through the browser (kodex.core.auth.apps): the app keeps [verifier] and
 * [state], and sends [challenge] (the base64url SHA-256 of the verifier) to /app-login.
 */
class Pkce private constructor(val verifier: String, val state: String) {
    val challenge: String = challengeOf(verifier)

    /** Whether a `kodex://login` return is the answer to this login. */
    fun answers(returnedState: String?): Boolean =
        returnedState != null && MessageDigest.isEqual(returnedState.toByteArray(), state.toByteArray())

    companion object {
        private val random = SecureRandom()
        private val base64 = Base64.getUrlEncoder().withoutPadding()

        fun new(): Pkce = Pkce(token(48), token(24))

        fun restore(verifier: String, state: String): Pkce = Pkce(verifier, state)

        fun challengeOf(verifier: String): String =
            base64.encodeToString(MessageDigest.getInstance("SHA-256").digest(verifier.toByteArray()))

        private fun token(bytes: Int): String = ByteArray(bytes).also(random::nextBytes).let(base64::encodeToString)
    }
}
