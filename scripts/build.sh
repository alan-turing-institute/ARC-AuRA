#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"

# Create the litmcp cache folder as the current user. It's gitignored, so on a fresh
# checkout it doesn't exist, and Docker would otherwise create it owned by root.
mkdir -p "$PROJECT_ROOT/litmcp/cache"

compose build agent litmcp
