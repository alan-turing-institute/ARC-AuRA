#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"

TASK="$1"; shift                       # e.g. task_03; the rest is the harness command
RUN_ID="$(date +%Y%m%d-%H%M%S)-${TASK}-${RANDOM}"
export RUN_DIR="$PROJECT_ROOT/runs/$RUN_ID"
mkdir -p "$RUN_DIR/workspace"

# Tell the harness where the literature server is
cp "$PROJECT_ROOT/mcp.json" "$RUN_DIR/workspace/.mcp.json"

# Temporary shortcut: see the note below
export RUN_KEY="${LITELLM_MASTER_KEY:?Set LITELLM_MASTER_KEY in ~/.zshrc}"

# Record what was run, then run it
printf 'image=research-sandbox:%s\ntask=%s\ncommand=%s\n' \
  "$AGENT_TAG" "$TASK" "$*" > "$RUN_DIR/run_info.txt"
compose run --rm agent "$@" 2>&1 | tee "$RUN_DIR/log.txt"
echo "Finished: $RUN_DIR"
