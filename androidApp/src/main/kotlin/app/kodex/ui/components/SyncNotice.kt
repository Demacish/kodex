package app.kodex.ui.components

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import app.kodex.R
import app.kodex.sync.SyncProblem
import app.kodex.sync.SyncStatus
import app.kodex.ui.AppViewModel

@Composable
fun SyncProblem.message(): String = when (this) {
    SyncProblem.Unreachable -> stringResource(R.string.sync_unreachable)
    SyncProblem.Unreadable -> stringResource(R.string.sync_unreadable)
    is SyncProblem.Server -> stringResource(R.string.sync_server_error, status)
}

/**
 * An empty list that may only be empty because nothing has come yet: while the first sync is
 * under way it says so, and when syncing fails it says why, with a way to try again.
 */
@Composable
fun EmptyCatalog(text: String, app: AppViewModel, modifier: Modifier = Modifier) {
    val synced by app.syncState.collectAsStateWithLifecycle(initialValue = null)
    val status by app.syncStatus.collectAsStateWithLifecycle(initialValue = SyncStatus())
    val problem = status.problem
    when {
        status.busy && synced?.syncedAt == null -> Notice(modifier.testTag("first-sync")) {
            CircularProgressIndicator()
            Text(stringResource(R.string.sync_fetching), textAlign = TextAlign.Center, style = MaterialTheme.typography.bodyLarge)
        }
        problem != null && !status.busy -> Notice(modifier.testTag("sync-problem")) {
            Text(problem.message(), textAlign = TextAlign.Center, style = MaterialTheme.typography.bodyLarge, color = MaterialTheme.colorScheme.error)
            OutlinedButton(onClick = app::syncNow) { Text(stringResource(R.string.sync_try_again)) }
        }
        else -> Empty(text, modifier)
    }
}

@Composable
private fun Notice(modifier: Modifier, content: @Composable () -> Unit) {
    Column(
        modifier.fillMaxSize().padding(32.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp, Alignment.CenterVertically),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) { content() }
}
