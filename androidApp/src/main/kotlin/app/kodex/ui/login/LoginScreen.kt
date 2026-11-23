package app.kodex.ui.login

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.automirrored.filled.ArrowForward
import androidx.compose.material.icons.automirrored.filled.Login
import androidx.compose.material.icons.automirrored.filled.OpenInNew
import androidx.compose.material.icons.filled.AdminPanelSettings
import androidx.compose.material.icons.filled.Dns
import androidx.compose.material.icons.filled.ErrorOutline
import androidx.compose.material.icons.filled.Key
import androidx.compose.material.icons.filled.Lock
import androidx.compose.material.icons.filled.LockOpen
import androidx.compose.material.icons.filled.Mail
import androidx.compose.material.icons.filled.Person
import androidx.compose.material.icons.filled.Shield
import androidx.compose.material.icons.filled.Timer
import androidx.compose.material.icons.filled.Visibility
import androidx.compose.material.icons.filled.VisibilityOff
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalUriHandler
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import app.kodex.R
import app.kodex.ui.components.Overline
import app.kodex.ui.theme.KodexTheme
import kotlinx.coroutines.delay

/** How long the app waits for the browser to come back before it gives up (the server's ticket lasts as long). */
private const val BROWSER_WAIT_MS = 5 * 60 * 1000L

class LoginActions(
    val setServer: (String) -> Unit = {},
    val connect: () -> Unit = {},
    val login: (String, String) -> Unit = { _, _ -> },
    val secondStep: (String) -> Unit = {},
    val browser: () -> Unit = {},
    val cancelBrowser: (Boolean) -> Unit = {},
    val setup: (String, String, String, String) -> Unit = { _, _, _, _ -> },
)

@Composable
fun LoginScreen(vm: LoginViewModel) {
    val state by vm.state.collectAsStateWithLifecycle()
    LoginContent(
        state,
        LoginActions(
            setServer = vm::setServer,
            connect = vm::connect,
            login = vm::login,
            secondStep = vm::secondStep,
            browser = vm::browser,
            cancelBrowser = { vm.cancelBrowser(it) },
            setup = vm::setup,
        ),
    )
}

/**
 * Logging in, one step at a time (the 2.4 look): the server's address, then the password (and the
 * code with two-step login) or the browser (passkeys, the identity provider), and the first admin
 * on a server that has none.
 */
@Composable
fun LoginContent(state: LoginState, actions: LoginActions) {
    val colors = KodexTheme.colors
    Surface(Modifier.fillMaxSize(), color = colors.background) {
        Column(
            Modifier.fillMaxSize().safeDrawingPadding().imePadding().verticalScroll(rememberScrollState()).padding(24.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Column(Modifier.widthIn(max = 440.dp).fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(16.dp)) {
                val config = state.config
                if (config != null) ServerChip(state.server) { actions.setServer(state.server) }
                if (state.busy) LinearProgressIndicator(Modifier.fillMaxWidth())
                when {
                    config == null -> Connect(state, actions)
                    state.browserSince != null -> Waiting(state.browserSince, actions)
                    state.ticket != null -> SecondStep(state, actions)
                    config.setupRequired -> Setup(state, config.setupCodeRequired, actions)
                    else -> Password(state, config.localLogin, config.passkeys, config.oidc, config.oidcName, actions)
                }
                state.error?.let { error ->
                    Problem(
                        when (error) {
                            LoginError.NotKodex -> stringResource(R.string.login_not_kodex)
                            LoginError.Unreachable -> stringResource(R.string.login_unreachable)
                            LoginError.BrowserTimedOut -> stringResource(R.string.login_browser_failed)
                            is LoginError.Refused -> error.detail.ifBlank { stringResource(R.string.login_refused) }
                        },
                    )
                }
            }
        }
    }
}

/** A step's icon in a soft square, its title and a line about it, centred. */
@Composable
private fun StepHead(icon: ImageVector, title: String, text: String, ring: Boolean = false) {
    val colors = KodexTheme.colors
    Column(Modifier.fillMaxWidth().padding(top = 16.dp), horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Box(contentAlignment = Alignment.Center) {
            if (ring) CircularProgressIndicator(Modifier.size(104.dp), strokeWidth = 3.dp, trackColor = colors.surface3)
            Box(Modifier.size(72.dp).clip(RoundedCornerShape(22.dp)).background(colors.accentSoft), contentAlignment = Alignment.Center) {
                Icon(icon, contentDescription = null, tint = colors.accentText, modifier = Modifier.size(34.dp))
            }
        }
        Text(title, style = MaterialTheme.typography.headlineMedium, color = colors.text, textAlign = TextAlign.Center)
        Text(text, style = MaterialTheme.typography.bodyMedium, color = colors.textMuted, textAlign = TextAlign.Center)
    }
}

/** The server being logged in to, as a chip with a way back to the address. */
@Composable
private fun ServerChip(server: String, onBack: () -> Unit) {
    val colors = KodexTheme.colors
    Row(verticalAlignment = Alignment.CenterVertically) {
        IconButton(onClick = onBack, modifier = Modifier.testTag("login-back")) {
            Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = stringResource(R.string.back), tint = colors.text)
        }
        Row(
            Modifier.weight(1f, fill = false).clip(CircleShape).background(colors.surface1).border(1.dp, colors.border, CircleShape)
                .padding(horizontal = 12.dp, vertical = 6.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(6.dp),
        ) {
            val secure = server.startsWith("https://")
            Icon(if (secure) Icons.Filled.Lock else Icons.Filled.LockOpen, contentDescription = null,
                tint = if (secure) colors.offline else colors.textFaint, modifier = Modifier.size(14.dp))
            Text(server.removePrefix("https://").removePrefix("http://"), style = MaterialTheme.typography.labelMedium, color = colors.textMuted,
                maxLines = 1, overflow = TextOverflow.Ellipsis)
        }
    }
}

/** What went wrong, in a red card. */
@Composable
private fun Problem(text: String) {
    val colors = KodexTheme.colors
    Row(
        Modifier.fillMaxWidth().clip(MaterialTheme.shapes.medium).background(colors.dangerSoft).padding(14.dp).testTag("login-error"),
        horizontalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        Icon(Icons.Filled.ErrorOutline, contentDescription = null, tint = colors.danger, modifier = Modifier.size(20.dp))
        Text(text, style = MaterialTheme.typography.bodyMedium, color = colors.danger)
    }
}

@Composable
private fun Field(
    value: String,
    onValue: (String) -> Unit,
    label: String,
    icon: ImageVector,
    tag: String,
    keyboard: KeyboardOptions = KeyboardOptions.Default,
    secret: Boolean = false,
) {
    var shown by rememberSaveable { mutableStateOf(false) }
    OutlinedTextField(
        value = value,
        onValueChange = onValue,
        label = { Text(label) },
        leadingIcon = { Icon(icon, contentDescription = null) },
        trailingIcon = if (secret) {
            {
                IconButton(onClick = { shown = !shown }) {
                    Icon(if (shown) Icons.Filled.VisibilityOff else Icons.Filled.Visibility,
                        contentDescription = stringResource(if (shown) R.string.login_hide_password else R.string.login_show_password))
                }
            }
        } else {
            null
        },
        visualTransformation = if (secret && !shown) PasswordVisualTransformation() else VisualTransformation.None,
        singleLine = true,
        keyboardOptions = keyboard,
        shape = MaterialTheme.shapes.medium,
        modifier = Modifier.fillMaxWidth().testTag(tag),
    )
}

@Composable
private fun Connect(state: LoginState, actions: LoginActions) {
    StepHead(Icons.Filled.Dns, stringResource(R.string.login_connect_title), stringResource(R.string.login_intro))
    Overline(stringResource(R.string.login_server))
    Field(state.server, actions.setServer, stringResource(R.string.login_server), Icons.Filled.Dns, "server",
        KeyboardOptions(keyboardType = KeyboardType.Uri, imeAction = ImeAction.Go))
    Button(
        onClick = actions.connect,
        enabled = state.server.isNotBlank() && !state.busy,
        modifier = Modifier.fillMaxWidth().heightIn(min = 52.dp).testTag("connect"),
    ) {
        Text(stringResource(R.string.login_connect))
        Spacer(Modifier.size(8.dp))
        Icon(Icons.AutoMirrored.Filled.ArrowForward, contentDescription = null, modifier = Modifier.size(18.dp))
    }
}

@Composable
private fun Password(state: LoginState, local: Boolean, passkeys: Boolean, oidc: Boolean, oidcName: String, actions: LoginActions) {
    val colors = KodexTheme.colors
    StepHead(Icons.AutoMirrored.Filled.Login, stringResource(R.string.login_title), stringResource(R.string.login_subtitle))
    if (local) {
        var username by rememberSaveable { mutableStateOf("") }
        var password by rememberSaveable { mutableStateOf("") }
        Field(username, { username = it }, stringResource(R.string.login_username), Icons.Filled.Person, "username")
        Field(password, { password = it }, stringResource(R.string.login_password), Icons.Filled.Lock, "password",
            KeyboardOptions(keyboardType = KeyboardType.Password, imeAction = ImeAction.Done), secret = true)
        Button(
            onClick = { actions.login(username, password) },
            enabled = username.isNotBlank() && password.isNotEmpty() && !state.busy,
            modifier = Modifier.fillMaxWidth().heightIn(min = 52.dp).testTag("login"),
        ) { Text(stringResource(R.string.login_button)) }
    }
    if (passkeys || oidc || !local) {
        if (local) {
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                HorizontalDivider(Modifier.weight(1f))
                Overline(stringResource(R.string.login_or))
                HorizontalDivider(Modifier.weight(1f))
            }
        }
        if (passkeys) {
            OutlinedButton(onClick = actions.browser, enabled = !state.busy, modifier = Modifier.fillMaxWidth().heightIn(min = 52.dp).testTag("passkey")) {
                Icon(Icons.Filled.Key, contentDescription = null, modifier = Modifier.size(18.dp))
                Spacer(Modifier.size(8.dp))
                Text(stringResource(R.string.login_passkey))
            }
        }
        if (oidc || (!passkeys && !local)) {
            OutlinedButton(onClick = actions.browser, enabled = !state.busy, modifier = Modifier.fillMaxWidth().heightIn(min = 52.dp).testTag("browser")) {
                Icon(Icons.AutoMirrored.Filled.OpenInNew, contentDescription = null, modifier = Modifier.size(18.dp))
                Spacer(Modifier.size(8.dp))
                Text(if (oidc && oidcName.isNotBlank()) stringResource(R.string.login_with, oidcName) else stringResource(R.string.login_browser))
            }
        }
        Text(stringResource(R.string.login_browser_help), style = MaterialTheme.typography.bodySmall, color = colors.textMuted,
            textAlign = TextAlign.Center, modifier = Modifier.fillMaxWidth())
    }
}

/** The six digits from the authenticator app, a box each (or a recovery code in a field). */
@Composable
private fun SecondStep(state: LoginState, actions: LoginActions) {
    val colors = KodexTheme.colors
    var code by rememberSaveable { mutableStateOf("") }
    var recovery by rememberSaveable { mutableStateOf(false) }
    StepHead(Icons.Filled.Shield, stringResource(R.string.login_second_title), stringResource(R.string.login_second_step))
    if (recovery) {
        Field(code, { code = it }, stringResource(R.string.login_code), Icons.Filled.Key, "code",
            KeyboardOptions(keyboardType = KeyboardType.Ascii, imeAction = ImeAction.Done))
    } else {
        BasicTextField(
            value = code,
            onValueChange = { next -> code = next.filter { it.isDigit() }.take(6) },
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.NumberPassword, imeAction = ImeAction.Done),
            modifier = Modifier.fillMaxWidth().testTag("code"),
            decorationBox = {
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp, Alignment.CenterHorizontally)) {
                    (0 until 6).forEach { i ->
                        val digit = code.getOrNull(i)
                        val current = i == code.length
                        Box(
                            Modifier.size(width = 46.dp, height = 56.dp).clip(MaterialTheme.shapes.small).background(colors.surface1)
                                .border(if (current) 2.dp else 1.dp, if (current) colors.accent else colors.border, MaterialTheme.shapes.small),
                            contentAlignment = Alignment.Center,
                        ) {
                            Text(digit?.toString() ?: "", style = MaterialTheme.typography.headlineSmall, color = colors.text)
                        }
                    }
                }
            },
        )
    }
    TextButton(onClick = {
        recovery = !recovery
        code = ""
    }, modifier = Modifier.fillMaxWidth()) {
        Text(stringResource(if (recovery) R.string.login_use_app_code else R.string.login_use_recovery))
    }
    Button(
        onClick = { actions.secondStep(code) },
        enabled = (if (recovery) code.isNotBlank() else code.length == 6) && !state.busy,
        modifier = Modifier.fillMaxWidth().heightIn(min = 52.dp).testTag("confirm-code"),
    ) { Text(stringResource(R.string.login_confirm)) }
    TextButton(onClick = { actions.setServer(state.server) }, modifier = Modifier.fillMaxWidth()) { Text(stringResource(R.string.login_start_over)) }
}

/** The browser is open: waiting for it to come back, with how long it may take. */
@Composable
private fun Waiting(since: Long, actions: LoginActions) {
    val colors = KodexTheme.colors
    var now by remember { mutableLongStateOf(System.currentTimeMillis()) }
    LaunchedEffect(since) {
        while (true) {
            now = System.currentTimeMillis()
            if (now - since >= BROWSER_WAIT_MS) {
                actions.cancelBrowser(true)
                break
            }
            delay(1_000)
        }
    }
    val left = ((BROWSER_WAIT_MS - (now - since)).coerceAtLeast(0) / 1000).toInt()
    StepHead(Icons.AutoMirrored.Filled.OpenInNew, stringResource(R.string.login_waiting_title), stringResource(R.string.login_waiting_text), ring = true)
    OutlinedButton(onClick = actions.browser, modifier = Modifier.fillMaxWidth().heightIn(min = 52.dp).testTag("browser-again")) {
        Icon(Icons.AutoMirrored.Filled.OpenInNew, contentDescription = null, modifier = Modifier.size(18.dp))
        Spacer(Modifier.size(8.dp))
        Text(stringResource(R.string.login_reopen))
    }
    TextButton(onClick = { actions.cancelBrowser(false) }, modifier = Modifier.fillMaxWidth().testTag("browser-cancel")) {
        Text(stringResource(R.string.login_cancel))
    }
    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.Center, verticalAlignment = Alignment.CenterVertically) {
        Icon(Icons.Filled.Timer, contentDescription = null, tint = colors.textFaint, modifier = Modifier.size(16.dp))
        Spacer(Modifier.size(6.dp))
        Text(stringResource(R.string.login_waiting_left, "%d:%02d".format(left / 60, left % 60)), style = MaterialTheme.typography.labelMedium,
            color = colors.textFaint)
    }
}

/** A server without an admin: the first one is made here (or in the browser, as before). */
@Composable
private fun Setup(state: LoginState, codeRequired: Boolean, actions: LoginActions) {
    val colors = KodexTheme.colors
    val uri = LocalUriHandler.current
    var username by rememberSaveable { mutableStateOf("") }
    var email by rememberSaveable { mutableStateOf("") }
    var password by rememberSaveable { mutableStateOf("") }
    var code by rememberSaveable { mutableStateOf("") }
    StepHead(Icons.Filled.AdminPanelSettings, stringResource(R.string.login_setup_title), stringResource(R.string.login_setup_text))
    Field(username, { username = it }, stringResource(R.string.login_username), Icons.Filled.Person, "setup-username")
    Field(email, { email = it }, stringResource(R.string.login_email), Icons.Filled.Mail, "setup-email",
        KeyboardOptions(keyboardType = KeyboardType.Email))
    Field(password, { password = it }, stringResource(R.string.login_password), Icons.Filled.Lock, "setup-password",
        KeyboardOptions(keyboardType = KeyboardType.Password), secret = true)
    Text(stringResource(R.string.login_password_hint), style = MaterialTheme.typography.bodySmall, color = colors.textMuted)
    if (codeRequired) {
        Field(code, { code = it }, stringResource(R.string.login_setup_code), Icons.Filled.Key, "setup-code",
            KeyboardOptions(keyboardType = KeyboardType.Ascii))
    }
    Button(
        onClick = { actions.setup(username, password, email, code) },
        enabled = username.isNotBlank() && password.length >= 8 && (!codeRequired || code.isNotBlank()) && !state.busy,
        modifier = Modifier.fillMaxWidth().heightIn(min = 52.dp).testTag("setup-create"),
    ) { Text(stringResource(R.string.login_setup_create)) }
    TextButton(onClick = { uri.openUri(state.server) }, modifier = Modifier.fillMaxWidth().testTag("setup")) {
        Text(stringResource(R.string.login_setup_open))
    }
    Spacer(Modifier.height(4.dp))
}
