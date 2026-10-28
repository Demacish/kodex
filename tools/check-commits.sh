#!/usr/bin/env bash
# Fails if a commit subject in the given range isn't a Conventional Commit
# (https://www.conventionalcommits.org): type(scope)!: description
#   tools/check-commits.sh origin/main..HEAD
set -euo pipefail
range="${1:?usage: check-commits.sh <revision range>}"
pattern='^(build|chore|ci|docs|feat|fix|perf|refactor|revert|style|test)(\([a-z0-9-]+\))?!?: .+'
subjects="$(git log --no-merges --format=%s "$range")"
bad=0
while IFS= read -r subject; do
  [ -z "$subject" ] && continue
  if ! [[ "$subject" =~ $pattern ]]; then
    echo "Not a Conventional Commit: $subject" >&2
    bad=1
  fi
done <<< "$subjects"
exit "$bad"
