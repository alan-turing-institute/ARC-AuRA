# Shared setup for scripts in this folder. Source this; don't run it directly.

# Absolute path to the project root (the folder above this file)
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Load versions.env and pass its variables on to Docker
VERSIONS_FILE="$PROJECT_ROOT/versions.env"
if [[ ! -f "$VERSIONS_FILE" ]]; then
  echo "Error: $VERSIONS_FILE not found" >&2
  exit 1
fi
set -a; source "$VERSIONS_FILE"; set +a
: "${AGENT_TAG:?AGENT_TAG is not set in versions.env}"

# Always use this project's compose file, wherever the script was run from
compose() {
  docker compose -f "$PROJECT_ROOT/docker-compose.yml" "$@"
}