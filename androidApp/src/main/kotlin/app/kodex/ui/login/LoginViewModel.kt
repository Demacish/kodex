package app.kodex.ui.login

import android.content.Context
import androidx.browser.customtabs.CustomTabsIntent
import androidx.core.net.toUri
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import app.kodex.account.AccountStore
import app.kodex.account.PendingBrowserLogin
import app.kodex.data.db.KodexDatabase
import app.kodex.download.Downloads
import app.kodex.shared.api.AppKey
import app.kodex.shared.api.AuthConfig
import app.kodex.shared.api.KodexApi
import app.kodex.shared.api.KodexApiException
import app.kodex.shared.auth.Pkce
import app.kodex.sync.ApiProvider
import app.kodex.sync.SyncWorker
import app.kodex.ui.wipe
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/** Where the login is. */
data class LoginState(
    val server: String = "",
    val config: AuthConfig? = null,
    val busy: Boolean = false,
    /** The account needs the code from its authenticator app (or a recovery code). */
    val ticket: String? = null,
    val error: LoginError? = null,
)

sealed interface LoginError {
    data object NotKodex : LoginError

    data object Unreachable : LoginError

    data object BrowserTimedOut : LoginError

    data class Refused(val detail: String) : LoginError
}

/**
 * Logging in: the server's address first (GET /api/auth/config tells what it offers), then the
 * password (and a code with two-step login), or the browser for passkeys and the identity
 * provider (kodex.core.auth.apps). Either way the app ends up with a key of its own.
 */
class LoginViewModel(
    private val context: Context,
    private val accounts: AccountStore,
    private val apis: ApiProvider,
    private val db: KodexDatabase,
    private val downloads: Downloads,
) : ViewModel() {
    private val _state = MutableStateFlow(LoginState())
    val state: StateFlow<LoginState> = _state.asStateFlow()

    init {
        viewModelScope.launch {
            accounts.lastServer.first()?.let { last -> _state.update { if (it.server.isEmpty()) it.copy(server = last) else it } }
        }
    }

    fun setServer(value: String) = _state.update { it.copy(server = value, config = null, error = null, ticket = null) }

    private fun normalized(server: String): String {
        val trimmed = server.trim().trimEnd('/')
        return if (trimmed.startsWith("http://") || trimmed.startsWith("https://")) trimmed else "https://$trimmed"
    }

    fun connect() = work {
        val server = normalized(_state.value.server)
        val config = apis.anonymous(server).use { it.config() }
        _state.update { it.copy(server = server, config = config) }
    }

    fun login(username: String, password: String) = work {
        val server = _state.value.server
        val answer = apis.anonymous(server).use { it.login(username.trim(), password, accounts.deviceName) }
        val key = answer.key
        if (key != null) finish(server, key) else _state.update { it.copy(ticket = answer.secondStep?.ticket) }
    }

    fun secondStep(code: String) = work {
        val server = _state.value.server
        val ticket = _state.value.ticket ?: return@work
        finish(server, apis.anonymous(server).use { it.secondStep(ticket, code.trim()) })
    }

    /** Opens the server's /app-login in a browser tab; it comes back to [finishBrowser]. */
    fun browser() = work {
        val server = _state.value.server
        val login = Pkce.new()
        accounts.startBrowserLogin(PendingBrowserLogin(server, login.verifier, login.state))
        val url = apis.anonymous(server).use { it.approveUrl(accounts.deviceName, login.challenge, login.state) }
        CustomTabsIntent.Builder().build().apply { intent.addFlags(android.content.Intent.FLAG_ACTIVITY_NEW_TASK) }
            .launchUrl(context, url.toUri())
    }

    fun finishBrowser(code: String?, state: String?) = work {
        val pending = accounts.pendingBrowserLogin()
        val login = pending?.let { Pkce.restore(it.verifier, it.state) }
        if (code == null || login == null || !login.answers(state)) {
            _state.update { it.copy(error = LoginError.BrowserTimedOut) }
            return@work
        }
        _state.update { it.copy(server = pending.server) }
        finish(pending.server, apis.anonymous(pending.server).use { it.token(code, login.verifier) })
    }

    private suspend fun finish(server: String, key: AppKey) {
        val me = KodexApi(server, { key.key }, engine = apis.engine).use { it.me() }
        val owner = "${me.username}@$server"
        val before = db.state().state()?.owner
        if (before != null && before.isNotEmpty() && before != owner) wipe(db, downloads)
        accounts.save(server, key.key, me.username)
        SyncWorker.schedule(context)
        SyncWorker.now(context)
        _state.value = LoginState(server = server)
    }

    private fun work(block: suspend () -> Unit) {
        viewModelScope.launch {
            _state.update { it.copy(busy = true, error = null) }
            try {
                block()
            } catch (e: CancellationException) {
                throw e
            } catch (e: KodexApiException) {
                _state.update { it.copy(error = if (e.status == 404) LoginError.NotKodex else LoginError.Refused(e.message.orEmpty())) }
            } catch (e: kotlinx.serialization.SerializationException) {
                _state.update { it.copy(error = LoginError.NotKodex) }
            } catch (e: Exception) {
                _state.update { it.copy(error = LoginError.Unreachable) }
            } finally {
                _state.update { it.copy(busy = false) }
            }
        }
    }
}

private inline fun <T> KodexApi.use(block: (KodexApi) -> T): T = try {
    block(this)
} finally {
    close()
}
