package app.kodex.ui.login

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalUriHandler
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import app.kodex.R
import app.kodex.ui.components.Logo
import app.kodex.ui.theme.KodexTheme

@Composable
fun LoginScreen(vm: LoginViewModel) {
    val state by vm.state.collectAsStateWithLifecycle()
    Surface(Modifier.fillMaxSize()) {
        Column(
            Modifier.fillMaxSize().safeDrawingPadding().imePadding().verticalScroll(rememberScrollState()).padding(24.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(16.dp),
        ) {
            Column(Modifier.widthIn(max = 420.dp).fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(16.dp)) {
                Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(14.dp)) {
                    Logo(size = 52.dp)
                    Text(stringResource(R.string.app_name), style = MaterialTheme.typography.displaySmall, color = KodexTheme.colors.accentText)
                }
                Text(stringResource(R.string.login_intro), style = MaterialTheme.typography.bodyLarge, color = KodexTheme.colors.textMuted)
                if (state.busy) LinearProgressIndicator(Modifier.fillMaxWidth())
                OutlinedTextField(
                    value = state.server,
                    onValueChange = vm::setServer,
                    label = { Text(stringResource(R.string.login_server)) },
                    placeholder = { Text("kodex.example.org") },
                    singleLine = true,
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri, imeAction = ImeAction.Go),
                    modifier = Modifier.fillMaxWidth().testTag("server"),
                )
                val config = state.config
                when {
                    config == null -> Button(
                        onClick = vm::connect,
                        enabled = state.server.isNotBlank() && !state.busy,
                        modifier = Modifier.fillMaxWidth().testTag("connect"),
                    ) { Text(stringResource(R.string.login_connect)) }
                    state.ticket != null -> SecondStep(vm, state.busy)
                    // Nobody can log in yet: the admin is chosen on the server's first page.
                    config.setupRequired -> {
                        val uri = LocalUriHandler.current
                        Text(stringResource(R.string.login_setup_needed), style = MaterialTheme.typography.bodyMedium)
                        Button(onClick = { uri.openUri(state.server) }, modifier = Modifier.fillMaxWidth().testTag("setup")) {
                            Text(stringResource(R.string.login_setup_open))
                        }
                        TextButton(onClick = vm::connect, enabled = !state.busy) { Text(stringResource(R.string.login_setup_again)) }
                    }
                    else -> {
                        if (config.localLogin) Password(vm, state.busy)
                        if (config.passkeys || config.oidc || !config.localLogin) {
                            if (config.localLogin) HorizontalDivider()
                            OutlinedButton(onClick = vm::browser, enabled = !state.busy, modifier = Modifier.fillMaxWidth().testTag("browser")) {
                                Text(
                                    when {
                                        config.oidc && config.oidcName.isNotBlank() -> stringResource(R.string.login_with, config.oidcName)
                                        config.passkeys -> stringResource(R.string.login_passkey)
                                        else -> stringResource(R.string.login_browser)
                                    },
                                )
                            }
                            Text(stringResource(R.string.login_browser_help), style = MaterialTheme.typography.bodySmall)
                        }
                    }
                }
                state.error?.let { error ->
                    Text(
                        when (error) {
                            LoginError.NotKodex -> stringResource(R.string.login_not_kodex)
                            LoginError.Unreachable -> stringResource(R.string.login_unreachable)
                            LoginError.BrowserTimedOut -> stringResource(R.string.login_browser_failed)
                            is LoginError.Refused -> error.detail.ifBlank { stringResource(R.string.login_refused) }
                        },
                        color = MaterialTheme.colorScheme.error,
                        modifier = Modifier.testTag("login-error"),
                    )
                }
            }
        }
    }
}

@Composable
private fun Password(vm: LoginViewModel, busy: Boolean) {
    var username by rememberSaveable { mutableStateOf("") }
    var password by rememberSaveable { mutableStateOf("") }
    OutlinedTextField(
        value = username,
        onValueChange = { username = it },
        label = { Text(stringResource(R.string.login_username)) },
        singleLine = true,
        modifier = Modifier.fillMaxWidth().testTag("username"),
    )
    OutlinedTextField(
        value = password,
        onValueChange = { password = it },
        label = { Text(stringResource(R.string.login_password)) },
        singleLine = true,
        visualTransformation = PasswordVisualTransformation(),
        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password, imeAction = ImeAction.Done),
        modifier = Modifier.fillMaxWidth().testTag("password"),
    )
    Button(
        onClick = { vm.login(username, password) },
        enabled = username.isNotBlank() && password.isNotEmpty() && !busy,
        modifier = Modifier.fillMaxWidth().testTag("login"),
    ) { Text(stringResource(R.string.login_button)) }
}

@Composable
private fun SecondStep(vm: LoginViewModel, busy: Boolean) {
    var code by rememberSaveable { mutableStateOf("") }
    Text(stringResource(R.string.login_second_step), style = MaterialTheme.typography.bodyMedium)
    OutlinedTextField(
        value = code,
        onValueChange = { code = it },
        label = { Text(stringResource(R.string.login_code)) },
        singleLine = true,
        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Ascii, imeAction = ImeAction.Done),
        modifier = Modifier.fillMaxWidth().testTag("code"),
    )
    Button(onClick = { vm.secondStep(code) }, enabled = code.isNotBlank() && !busy, modifier = Modifier.fillMaxWidth()) {
        Text(stringResource(R.string.login_confirm))
    }
    TextButton(onClick = { vm.setServer(vm.state.value.server) }) { Text(stringResource(R.string.login_start_over)) }
}
