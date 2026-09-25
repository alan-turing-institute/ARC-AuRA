#!/usr/bin/env bash
set -euo pipefail
TASK="$1"; shift                       # e.g. task_03; the rest is the harness command
RUN_ID="$(date +%Y%m%d-%H%M%S)-${TASK}-${RANDOM}"
export RUN_DIR="$PWD/runs/$RUN_ID"
mkdir -p "$RUN_DIR/workspace"

# Tell the harness where the literature server is
# cp mcp.json "$RUN_DIR/workspace/.mcp.json"   # re-enable once litmcp exists

# Temporary shortcut: see the note below
export RUN_KEY="${LITELLM_MASTER_KEY:?Set LITELLM_MASTER_KEY in ~/.zshrc}"

# Record what was run, then run it
printf 'image=research-sandbox:0.1\ntask=%s\ncommand=%s\n' "$TASK" "$*" > "$RUN_DIR/run_info.txt"
docker compose run --rm agent "$@" 2>&1 | tee "$RUN_DIR/log.txt"
echo "Finished: $RUN_DIR"
