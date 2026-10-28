package app.kodex.shared

import app.kodex.shared.auth.Pkce
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class PkceTest {
    @Test
    fun theChallengeIsTheBase64urlSha256OfTheVerifier() {
        // RFC 7636, appendix B.
        assertEquals("E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM", Pkce.challengeOf("dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"))
    }

    @Test
    fun aNewLoginFitsWhatTheServerTakes() {
        val login = Pkce.new()
        assertTrue(Regex("^[A-Za-z0-9_-]{43,128}$").matches(login.verifier))
        assertTrue(Regex("^[A-Za-z0-9_-]{43}$").matches(login.challenge))
        assertTrue(login.answers(login.state))
        assertFalse(login.answers(Pkce.new().state))
        assertFalse(login.answers(null))
    }
}
