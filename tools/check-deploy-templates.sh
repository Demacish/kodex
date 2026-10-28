#!/usr/bin/env bash
# The NAS templates in deploy/ must say what docker-compose.yml says:
#   - deploy/portainer/docker-compose.yml is it without the build;
#   - the Unraid templates run the same image with the same paths.
set -euo pipefail
repo="$(cd "$(dirname "$0")/.." && pwd)"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
touch "$work/.env"
export POSTGRES_PASSWORD=x LIBRARIES_HOST_PATH=/books SORTED_LIBRARY_HOST_PATH=/sorted KODEX_ENV_FILE="$work/.env"

normal() {
  docker compose -p kodex -f "$1" --project-directory "$work" config --format json \
    | jq -S 'del(.name) | del(.services[].build)'
}
diff <(normal "$repo/docker-compose.yml") <(normal "$repo/deploy/portainer/docker-compose.yml")

image="$(normal "$repo/docker-compose.yml" | jq -r '.services.api.image')"
targets="$(normal "$repo/docker-compose.yml" | jq -r '.services.api.volumes[].target' | sort)"
for template in "$repo"/deploy/unraid/*.xml; do
  python3 -I - "$template" "$image" "$targets" <<'PY'
import sys
import xml.etree.ElementTree as ET

path, image, targets = sys.argv[1], sys.argv[2], sorted(sys.argv[3].split())
root = ET.parse(path).getroot()
assert root.findtext("Repository") == image, f"{path}: {root.findtext('Repository')} is not {image}"
paths = sorted(c.get("Target") for c in root.iter("Config") if c.get("Type") == "Path")
assert paths == targets, f"{path}: paths {paths}, compose has {targets}"
PY
done
echo "deploy/ matches docker-compose.yml"
