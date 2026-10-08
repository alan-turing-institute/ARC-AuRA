# ARC-AuRA

[![Actions Status][actions-badge]][actions-link]

ARC project on research agents

## Developer

1. Download and install `uv`:

2. Install Docker, using either Docker Desktop or Colima (a command-line-only alternative). Either way, give it at least 6 CPUs and 20GB of memory (YMMV).

**Docker Desktop:** download and install from <https://docs.docker.com/desktop/setup/install/mac-install/> (or use an appropriate install for Linux), then increase the resource limits in its settings.

**Colima (macOS):** install the Docker CLI, Compose and Colima with Homebrew, then start the Colima VM:

```bash
brew install docker docker-compose colima
colima start --cpu 6 --memory 20 --disk 100
```

Colima remembers these settings, so afterwards plain `colima start` is enough.

**Note:** Colima does not start or stop on its own. Once started, it keeps running in the background (even through sleep or closing the terminal) until you run `colima stop` or shut down your Mac. After a reboot, either run `colima start` before using Docker, or run `brew services start colima` to start it on login. If `docker compose` is not recognised, link the Compose plugin where Docker can find it:

```bash
mkdir -p ~/.docker/cli-plugins
ln -sfn /opt/homebrew/lib/docker/cli-plugins/docker-compose ~/.docker/cli-plugins/docker-compose
```

Verify the installation in a new terminal with

```bash
docker run --rm hello-world
```

followed by:

```bash
docker compose version
```

3. Create venv and install by running

```bash
uv sync
```

4. Activate the environment

```bash
source .venv/bin/activate
```

5. Install pre-commit

```bash
uv run pre-commit install
```

## Agent sandbox

Agents run in throwaway Docker containers with no internet access. Each run gets a fresh container, which is deleted when the run finishes. API keys never enter the container or the repo.

### Components

| Component | Config | Role |
|---|---|---|
| `agent` | `agent/Dockerfile` | Image the harness runs in (Claude Code + Python stack). One fresh container per run; sandbox network only. |
| `litellm` | `litellm/config.yaml` | Model gateway. Holds API keys and forwards model calls; agents only get a gateway key. |
| `proxy` | `proxy/squid.conf` | Manages agent website access. |
| `.env` | repo root | Agent image tag. Increment it whenever the image changes to keep old images cached. |
| `scripts/` | | `build.sh` builds the agent image; `run.sh` runs one task. |

### First time setup

1. Add the environment variables required by your chosen model. See </litellm/config.yaml> for options. For example, if using `claude-haiku-4-5`, you will need the following keys:

```bash
export AZURE_FOUNDRY_API_BASE="https://<resource>.services.ai.azure.com/anthropic"
export AZURE_FOUNDRY_API_KEY="<foundry key>"
export LITELLM_MASTER_KEY="sk-<output of: openssl rand -hex 24>"
```

Note the last of these is required across all models.

2. Get a Semantic Scholar API key for the literature server (`litmcp`). It works without one, but unauthenticated requests share a public rate limit and are often refused with HTTP 429.

   1. Make a few unauthenticated requests first, as the application form asks whether you have. For example:

      ```bash
      curl -s "https://api.semanticscholar.org/graph/v1/paper/search?query=transformers&limit=1&fields=title"
      ```

      If this returns `Too Many Requests`, wait a minute and try again.

   2. Apply at <https://www.semanticscholar.org/product/api#api-key-form>. The endpoints used are `/graph/v1/paper/search`, `/graph/v1/paper/{paper_id}` and `/graph/v1/paper/{paper_id}/citations`. Results are cached, so a few thousand requests per day is plenty.

   3. Once the key arrives by email, add it to `~/.zshrc` with your other keys, then run `source ~/.zshrc`. Never put it in the repo's `.env`, which is committed.

      ```bash
      export S2_API_KEY="<semantic scholar key>"
      ```

   4. Check the key is accepted. This should print `200`:

      ```bash
      curl -s -o /dev/null -w '%{http_code}\n' -H "x-api-key: $S2_API_KEY" \
        "https://api.semanticscholar.org/graph/v1/paper/search?query=transformers&limit=1"
      ```

3. Build the agent docker image:

```bash
./scripts/build.sh
```

### Each session

1. Startup the modelgateway and proxy and verify they are running. If using Colima, start it first with `colima start` (skip this if it is already running; check with `colima status`).

```bash
docker compose up -d litellm proxy   # start gateway and proxy
docker compose ps                    # both should be running
```

2. Once finished for the day, shut everything down aferwards with:

```bash
docker compose down
```

If using Colima, also stop the VM to free up its CPU and memory (it keeps running, even through sleep, until stopped):

```bash
colima stop
```

### Running a task

Tasks are run with the `./scripts/run.sh` script:

```bash
./scripts/run.sh <task> <command...>
```

For example:

```bash
./scripts/run.sh dummy_task claude -p "Read /data/dummy_task.md and complete the task. Write results to /workspace/results." \
  --output-format json --dangerously-skip-permissions
```

Each run creates `runs/<timestamp>-<task>-<n>/` containing:

- `workspace/`: everything the agent wrote
- `log.txt`: full output
- `run_info.txt`: image tag, task and command

Inside the container, the agent can read `/data` and `/skills` (read-only) and write to `/workspace`.

### Making changes

If making changes to the sandbox, some files require extra changes being made elsewhere:

| If you've changed | Then |
|---|---|
| `agent/Dockerfile` or `agent/requirements.txt` | increment `AGENT_TAG` in `.env`, then run `./scripts/build.sh` |
| `litellm/config.yaml` | run `docker compose restart litellm` |
| Keys in `~/.zshrc` | run `source ~/.zshrc`, then `docker compose up -d litellm` |

### Rules

- Only use `--dangerously-skip-permissions` (in `run.sh`) inside the sandbox; the container is what makes it safe.
- Never mount the Docker socket, your home folder or `~/.claude` into the agent container.
- Never commit keys: store in global environment only.

### Verifying the sandbox

If needing to check the sandbox is still secure (e.g. after making changes), run the following:

```bash
# 1. Gateway reachable → a short "alive" message
RUN_DIR="$TMPDIR" docker compose run --rm -T agent curl -s http://litellm:4000/health/liveliness

# 2. Model call works → a reply from the model
RUN_KEY="$LITELLM_MASTER_KEY" RUN_DIR="$TMPDIR" docker compose run --rm -T agent claude -p "Say hello" < /dev/null

# 3. Blocked site via proxy → 403
RUN_DIR="$TMPDIR" docker compose run --rm -T agent curl -sS https://example.com

# 4. No direct route out → connection error or timeout
RUN_DIR="$TMPDIR" docker compose run --rm -T agent curl --noproxy '*' --max-time 5 https://example.com

# 5. Package install via proxy → downloads successfully
RUN_DIR="$TMPDIR" docker compose run --rm -T agent pip download requests -d /tmp/x

# 6. Data is read-only → "Read-only file system"
RUN_DIR="$TMPDIR" docker compose run --rm -T agent touch /data/test

# 7. No secrets inside → no output # TODO: stop passing master key
#    (currently prints the master key lines; TODO: stop passing the master key)
RUN_KEY="$LITELLM_MASTER_KEY" RUN_DIR="$TMPDIR" docker compose run --rm -T agent env \
  | grep -F -e "$AZURE_FOUNDRY_API_KEY" -e "$LITELLM_MASTER_KEY"

# 8. Not root → uid=1000(agent)
RUN_DIR="$TMPDIR" docker compose run --rm -T agent id

# 9. Memory limit enforced → process killed or MemoryError
RUN_DIR="$TMPDIR" docker compose run --rm -T agent python -c "b = bytearray(20 * 1024**3)"

# 10. Fresh each run → first command succeeds; second says "No such file or directory"
RUN_DIR="$TMPDIR" docker compose run --rm -T agent touch /tmp/marker
RUN_DIR="$TMPDIR" docker compose run --rm -T agent ls /tmp/marker

# 11. Foundry not reachable directly → connection error or timeout (Foundry models only)
RUN_DIR="$TMPDIR" docker compose run --rm -T agent curl --noproxy '*' --max-time 5 https://<resource-name>.services.ai.azure.com
```

## License

Distributed under the terms of the [BSD license](LICENSE).
