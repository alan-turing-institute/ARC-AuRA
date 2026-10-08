# ARC-AuRA

[![Actions Status][actions-badge]][actions-link]

ARC project on research agents

## Developer

1. Download and install `uv`:

2. Download and install docker desktop from <https://docs.docker.com/desktop/setup/install/mac-install/> (or use an appropriate install for Linux). Increase resource limits to at least 6 CPUs and 20GB (YMMV). Verify the installation in a new terminal with

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
| `scripts/` | | `build.sh` builds the agent image. |
| `aura run` | `src/aura/` | Assembles a task prompt and runs it in a fresh agent container. |
| `tasks/` | | Task descriptions; see [Tasks](#tasks). |

### First time setup

1. Add the environment variables required by your chosen model. See </litellm/config.yaml> for options. For example, if using `claude-haiku-4-5`, you will need the following keys:

```bash
export AZURE_FOUNDRY_API_BASE="https://<resource>.services.ai.azure.com/anthropic"
export AZURE_FOUNDRY_API_KEY="<foundry key>"
export LITELLM_MASTER_KEY="sk-<output of: openssl rand -hex 24>"
```

Note the last of these is required across all models.

2. Build the agent docker image:

```bash
./scripts/build.sh
```

### Each session

1. Startup the modelgateway and proxy and verify they are running:

```bash
docker compose up -d litellm proxy   # start gateway and proxy
docker compose ps                    # both should be running
```

2. Once finished for the day, shut everything down aferwards with:

```bash
docker compose down
```

### Running a task

Tasks are run with `aura run`:

```bash
aura run <task> [--harness claude-code] [--model claude-haiku-4-5] [--task-tier 1]
```

For example:

```bash
aura run dummy_task
```

The task is passed to the agent inline in its prompt and also mounted read-only at `/task/TASK.md`, so the agent can reread it. Each run creates `runs/<timestamp>-<task>-<n>/` containing:

- `workspace/`: everything the agent wrote
- `task/TASK.md`: the task exactly as the agent received it
- `log.txt`: full output
- `run_config.json`: image tag, options and the full harness command

Inside the container, the agent can read `/skills` and `/task` (read-only) and write to `/workspace`.

### Tasks

Each task is a folder in `tasks/` with one markdown file per tier:

```
tasks/
  instructions.md            # shared prompt template; {task} is replaced by the task text
  <task>/
    requirement.md
    research_questions.md
    lit_review.md
    instructions.md          # optional; overrides the shared template
```

Tiers are numbered and stack in order: 1 = requirement, 2 = + research questions, 3 = + lit review. For example, `--task-tier 2` includes `requirement.md` and `research_questions.md`. Each section is wrapped in tags named after its file (e.g. `<requirement>…</requirement>`), and the shared template explains what each one is. Only the files up to the chosen tier need to exist.

### Making changes

If making changes to the sandbox, some files require extra changes being made elsewhere:

| If you've changed | Then |
|---|---|
| `agent/Dockerfile` or `agent/requirements.txt` | increment `AGENT_TAG` in `.env`, then run `./scripts/build.sh` |
| `litellm/config.yaml` | run `docker compose restart litellm` |
| Keys in `~/.zshrc` | run `source ~/.zshrc`, then `docker compose up -d litellm` |

### Rules

- Only use `--dangerously-skip-permissions` (in `aura run`) inside the sandbox; the container is what makes it safe.
- Never mount the Docker socket, your home folder or `~/.claude` into the agent container.
- Never commit keys: store in global environment only.

### Verifying the sandbox

If needing to check the sandbox is still secure (e.g. after making changes), run the following:

```bash
# 1. Gateway reachable → a short "alive" message
docker compose run --rm -T agent curl -s http://litellm:4000/health/liveliness

# 2. Model call works → a reply from the model
docker compose run --rm -T agent claude -p "Say hello" < /dev/null

# 3. Blocked site via proxy → 403
docker compose run --rm -T agent curl -sS https://example.com

# 4. No direct route out → connection error or timeout
docker compose run --rm -T agent curl --noproxy '*' --max-time 5 https://example.com

# 5. Package install via proxy → downloads successfully
docker compose run --rm -T agent pip download requests -d /tmp/x

# 6. No secrets inside → no output # TODO: stop passing master key
#    (currently prints the master key lines; TODO: stop passing the master key)
RUN_KEY="$LITELLM_MASTER_KEY" RUN_DIR="$TMPDIR" docker compose run --rm -T agent env \
  | grep -F -e "$AZURE_FOUNDRY_API_KEY" -e "$LITELLM_MASTER_KEY"

# 7. Not root → uid=1000(agent)
docker compose run --rm -T agent id

# 8. Memory limit enforced → process killed or MemoryError
docker compose run --rm -T agent python -c "b = bytearray(20 * 1024**3)"

# 9. Fresh each run → first command succeeds; second says "No such file or directory"
docker compose run --rm -T agent touch /tmp/marker
docker compose run --rm -T agent ls /tmp/marker

# 10. Foundry not reachable directly → connection error or timeout (Foundry models only)
docker compose run --rm -T agent curl --noproxy '*' --max-time 5 https://<resource-name>.services.ai.azure.com
```

## License

Distributed under the terms of the [BSD license](LICENSE).
