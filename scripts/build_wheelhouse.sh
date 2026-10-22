#!/usr/bin/env bash
# Rebuild the wheelhouse pypiserver serves from scratch: the allowlist and its
# dependencies, nothing else. Restarts pypiserver if it's running.
# Uses the agent's image so wheels match its Python version and CPU architecture.
# Names only, no --require-hashes; add hash pins before real runs.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"

WHEELHOUSE="$PROJECT_ROOT/pypi/wheelhouse"
STAGING="$PROJECT_ROOT/pypi/staging"

# Download into a clean staging folder, so a failed download leaves the current
# wheelhouse untouched. It's created as the current user; Docker would otherwise
# create it as root.
rm -rf "$STAGING"
mkdir -p "$STAGING" "$WHEELHOUSE"
docker run --rm --user "$(id -u):$(id -g)" \
  -v "$STAGING:/w" \
  -v "$PROJECT_ROOT/pypi/allowlist.txt:/allowlist.txt:ro" \
  "research-sandbox:$AGENT_TAG" \
  pip download --disable-pip-version-check --no-cache-dir -d /w -r /allowlist.txt

# Replace the wheelhouse's contents rather than the folder itself: pypiserver
# bind-mounts the folder, and would keep serving a replaced one
find "$WHEELHOUSE" -mindepth 1 -delete
mv "$STAGING"/* "$WHEELHOUSE"/
rmdir "$STAGING"

# Restart the mirror if it's running, so it serves the new set
if [[ -n "$(compose ps -q pypiserver)" ]]; then
  compose restart pypiserver
fi
ls "$WHEELHOUSE"
