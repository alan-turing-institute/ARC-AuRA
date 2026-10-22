#!/usr/bin/env bash
# Download the allowlist and its dependencies into the wheelhouse pypiserver serves.
# Uses the agent's image so wheels match its Python version and CPU architecture.
# Names only, no --require-hashes; add hash pins before real runs.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"

# Create the wheelhouse as the current user; Docker would otherwise create it as root
mkdir -p "$PROJECT_ROOT/pypi/wheelhouse"

docker run --rm --user "$(id -u):$(id -g)" \
  -v "$PROJECT_ROOT/pypi/wheelhouse:/w" \
  -v "$PROJECT_ROOT/pypi/allowlist.txt:/allowlist.txt:ro" \
  "research-sandbox:$AGENT_TAG" \
  pip download --disable-pip-version-check --no-cache-dir -d /w -r /allowlist.txt
ls "$PROJECT_ROOT/pypi/wheelhouse"
