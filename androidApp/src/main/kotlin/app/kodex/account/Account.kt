package app.kodex.account

import android.content.Context
import android.os.Build
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import java.security.KeyStore
import java.util.UUID
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.map

/** Who the app is logged in as: the server, the app's key on it, and this device. */
data class Session(val server: String, val key: String, val username: String, val deviceId: String, val deviceName: String) {
    /** The catalog on the device belongs to this account; another one starts from nothing. */
    val owner: String get() = "$username@$server"
}

/** A login through the browser that hasn't come back yet (it survives the app being killed). */
data class PendingBrowserLogin(val server: String, val verifier: String, val state: String)

/** Seals the API key with a key in the Android keystore, so the stored value is useless elsewhere. */
interface KeySealer {
    fun seal(plain: String): String

    fun open(sealed: String): String?
}

class KeystoreSealer : KeySealer {
    private val alias = "kodex-api-key"

    private fun key(): SecretKey {
        val store = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        (store.getKey(alias, null) as? SecretKey)?.let { return it }
        val generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore")
        generator.init(
            KeyGenParameterSpec.Builder(alias, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .build(),
        )
        return generator.generateKey()
    }

    override fun seal(plain: String): String {
        val cipher = Cipher.getInstance("AES/GCM/NoPadding").apply { init(Cipher.ENCRYPT_MODE, key()) }
        val sealed = cipher.iv + cipher.doFinal(plain.toByteArray())
        return Base64.encodeToString(sealed, Base64.NO_WRAP)
    }

    override fun open(sealed: String): String? = runCatching {
        val bytes = Base64.decode(sealed, Base64.NO_WRAP)
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.DECRYPT_MODE, key(), GCMParameterSpec(128, bytes, 0, 12))
        String(cipher.doFinal(bytes, 12, bytes.size - 12))
    }.getOrNull()
}

private val Context.accountData: DataStore<Preferences> by preferencesDataStore("account")

class AccountStore(private val context: Context, private val sealer: KeySealer) {
    private object Keys {
        val server = stringPreferencesKey("server")
        val key = stringPreferencesKey("key")
        val username = stringPreferencesKey("username")
        val deviceId = stringPreferencesKey("device_id")
        val pendingServer = stringPreferencesKey("pending_server")
        val pendingVerifier = stringPreferencesKey("pending_verifier")
        val pendingState = stringPreferencesKey("pending_state")
        val lastServer = stringPreferencesKey("last_server")
    }

    /** The device name the server shows next to the app's key and its reading positions. */
    val deviceName: String = listOf(Build.MANUFACTURER, Build.MODEL)
        .filter { it.isNotBlank() && it != "unknown" }
        .distinct()
        .joinToString(" ")
        .ifBlank { "Android" }
        .replaceFirstChar { it.uppercase() }
        .take(80)

    val session: Flow<Session?> = context.accountData.data.map { it.session() }

    val lastServer: Flow<String?> = context.accountData.data.map { it[Keys.lastServer] }

    suspend fun current(): Session? = context.accountData.data.first().session()

    private fun Preferences.session(): Session? {
        val server = this[Keys.server] ?: return null
        val key = this[Keys.key]?.let(sealer::open) ?: return null
        val deviceId = this[Keys.deviceId] ?: return null
        return Session(server, key, this[Keys.username].orEmpty(), deviceId, deviceName)
    }

    suspend fun save(server: String, key: String, username: String) {
        context.accountData.edit {
            it[Keys.server] = server
            it[Keys.lastServer] = server
            it[Keys.key] = sealer.seal(key)
            it[Keys.username] = username
            if (it[Keys.deviceId] == null) it[Keys.deviceId] = UUID.randomUUID().toString()
            it.remove(Keys.pendingServer)
            it.remove(Keys.pendingVerifier)
            it.remove(Keys.pendingState)
        }
    }

    suspend fun forget() {
        context.accountData.edit {
            it.remove(Keys.server)
            it.remove(Keys.key)
            it.remove(Keys.username)
        }
    }

    suspend fun startBrowserLogin(login: PendingBrowserLogin) {
        context.accountData.edit {
            it[Keys.pendingServer] = login.server
            it[Keys.pendingVerifier] = login.verifier
            it[Keys.pendingState] = login.state
        }
    }

    suspend fun pendingBrowserLogin(): PendingBrowserLogin? {
        val data = context.accountData.data.first()
        return PendingBrowserLogin(
            data[Keys.pendingServer] ?: return null,
            data[Keys.pendingVerifier] ?: return null,
            data[Keys.pendingState] ?: return null,
        )
    }
}
