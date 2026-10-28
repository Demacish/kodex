package app.kodex

import android.content.Intent
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import app.kodex.ui.KodexAppUi
import app.kodex.ui.login.LoginViewModel
import org.koin.androidx.viewmodel.ext.android.viewModel

class MainActivity : ComponentActivity() {
    private val login: LoginViewModel by viewModel()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        handle(intent)
        setContent { KodexAppUi(login) }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        handle(intent)
    }

    /** kodex://login?code=…&state=… : the browser approved this app. */
    private fun handle(intent: Intent?) {
        val data = intent?.data ?: return
        if (data.scheme == "kodex" && data.host == "login") {
            login.finishBrowser(data.getQueryParameter("code"), data.getQueryParameter("state"))
        }
    }
}
