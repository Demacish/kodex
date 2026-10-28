#!/usr/bin/env bash
# Rewrites backend/tests/golden/eval_baseline.json from the current engine.
# Run it only when a change is meant to move the evaluation, and say why
# in the commit.
set -euo pipefail
repo="$(cd "$(dirname "$0")/../.." && pwd)"
KODEX_TEST_CMD="python -m kodex.matching.eval --json" "$repo/tools/test-backend.sh" 2>/dev/null | python3 -c "
import json, sys
d = json.load(sys.stdin)
strata = {k: {'precision': v['precision'], 'recall': v['recall'], 'review_share': round(v['review_share'], 4), 'n': v['n']} for k, v in d.items()}
json.dump({'seed': 20261025, 'note': 'Baseline of python -m kodex.matching.eval; regenerate with tools/eval/update_baseline.sh when an intended change moves it.', 'strata': strata}, open('$repo/backend/tests/golden/eval_baseline.json', 'w'), indent=1)
print('updated')
"
