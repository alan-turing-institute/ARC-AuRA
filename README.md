# ARC-AuRA

[![Actions Status][actions-badge]][actions-link]

ARC project on research agents

## Developer

1. Download and install `uv`

2. Install the Docker CLI, Compose and Colima (or use another container runtime manager of your choosing, such as Docker Desktop):

```bash
brew install docker docker-compose colima
```

3. Start the Colima VM for the first time, giving it at least 6 CPUs and 20GB of memory (YMMV):

```bash
colima start --cpu 6 --memory 20 --disk 100
```

Colima remembers these settings, so afterwards plain `colima start` is enough.

**Note:** Colima does not start or stop on its own. Once started, it keeps running in the background (even through sleep or closing the terminal) until you run `colima stop` or shut down your Mac.

After a reboot, either run `colima start` before using Docker, or run `brew services start colima` to start it on login.

4. Verify the installation in a new terminal with

```bash
docker run --rm hello-world
```

followed by:

```bash
docker compose version
```

If `docker compose` is not recognised, add the path (`"/opt/homebrew/lib/docker/cli-plugins"` if installing with homebrew) to a list under the key `cliPluginsExtraDirs` in `~/.docker/config.json`.

The below command assumes this key isn't yet in the config and will overwrite it if it is present:

```bash
jq '.cliPluginsExtraDirs = ["/opt/homebrew/lib/docker/cli-plugins"]' \
  ~/.docker/config.json > /tmp/docker-config.json \
  && mv /tmp/docker-config.json ~/.docker/config.json
```

5. Create venv and install by running

```bash
uv sync
```

6. Activate the environment

```bash
source .venv/bin/activate
```

7. Install pre-commit

```bash
uv run pre-commit install
```

## Agent sandbox

Agents run with [Inspect](https://inspect.aisi.org.uk) in throwaway Docker containers with no internet access. Each run gets a fresh container, which is deleted when the run finishes. The harness's model calls go through Inspect's agent bridge to the host, so API keys never enter the container or the repo. Every tool call passes through an Inspect approval policy and is recorded in the run's `.eval` log.

### Components

| Component | Config | Role |
|---|---|---|
| `agent` | `agent/Dockerfile`, `agent/compose.yaml` | Image the harness runs in (Claude Code + OpenCode + Python stack), and the compose file Inspect uses to start one fresh container per run on the sandbox network. |
| `litellm` | `litellm/config.yaml` | Model gateway. Holds API keys and forwards model calls. Each run gets its own gateway key, limited to one model, a budget and an expiry. Published on `127.0.0.1:4000` only; only the host (`aura run` and Inspect) calls it, never the agent. |
| `postgres` | `docker-compose.yml` | LiteLLM's database: run keys and their spend. Only `litellm` can reach it; data persists in the `litellm_db` volume. |
| `pypiserver` | `pypi/allowlist.txt` | PyPI mirror. Serves only the wheels in `pypi/wheelhouse/`: the allowlisted packages and their dependencies. The agent's `pip` uses it; nothing else is installable. |
| `litmcp` | `litmcp/` | Literature MCP server. Searches Semantic Scholar and serves open-access paper text and page images to agents, caching every result in `litmcp/cache/`. Holds the Semantic Scholar key; agents only reach it over the sandbox network. |
| `mcp.json` | repo root | MCP config pointing the agent at `litmcp`. `aura run` passes it to either harness. |
| `approval.yaml` | repo root | Inspect approval policy: which approver handles each tool call. See [Approval](#approval). |
| `.env` | repo root | Agent image tag. Increment it whenever the image changes to keep old images cached. |
| `scripts/` | | `build.sh` builds the agent and `litmcp` images; `build_wheelhouse.sh` downloads the mirror's wheels. |
| `aura run` | `src/aura/` | Assembles a task prompt and runs it as an Inspect eval in a fresh agent container. |
| `tasks/` | | Task descriptions; see [Tasks](#tasks). |

### Code layout

| Module (`src/aura/`) | Role |
|---|---|
| `cli.py` | `aura` command-line entry point |
| `run.py` | Runs a task: builds the prompt, makes the run folder and chains the steps below |
| `task.py` | Assembles a task prompt from the files in `tasks/` |
| `evaluation.py` | Builds and runs the one-sample Inspect eval, and copies `/workspace` out |
| `gateway.py` | Per-run LiteLLM keys: creates, blocks and records the spend of each |
| `harnesses/` | One function per harness, each building an Inspect agent from a model name |
| `constants.py` | Paths, models (from `litellm/config.yaml`), tiers and stages |

### First time setup

1. Add the environment variables required by the models you will use. See </litellm/config.yaml> for options; each provider key it reads must also be listed under `litellm`'s `environment` in `docker-compose.yml`. For example, if using `claude-haiku-4-5`, you will need the following keys:

```bash
export AZURE_FOUNDRY_API_BASE="https://<resource>.services.ai.azure.com/anthropic"
export AZURE_FOUNDRY_API_KEY="<foundry key>"
export LITELLM_MASTER_KEY="sk-<output of: openssl rand -hex 24>"
export LITELLM_DB_PASSWORD="<output of: openssl rand -hex 24>"
```

Note the last two of these are required across all models. `LITELLM_DB_PASSWORD` is the password for LiteLLM's database; keep it hex, as other characters would need escaping in its connection URL.

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

3. Build the docker images (the agent and litmcp), then download the PyPI mirror's wheels (several GB, as the allowlist includes torch):

```bash
./scripts/build.sh
./scripts/build_wheelhouse.sh
```

### Each session

1. If not already started, startup colima:

```bash
colima start
```

2. Start the model gateway, literature server and PyPI mirror, and verify they are running:

```bash
docker compose up -d litellm litmcp pypiserver   # gateway (and its database), literature server, mirror
docker compose ps                                # all four should be running, postgres "healthy"
```

3. Once finished for the day, shut everything down aferwards with:

```bash
docker compose down
```

**Don't add `-v`:** `docker compose down -v` also deletes the `litellm_db` volume, and with it every run key and its cost history.

4. Stop the colima VM to free up its CPU and memory (it keeps running, even through sleep, until stopped):

```bash
colima stop
```

### Running a task

Tasks are run with `aura run`:

```bash
aura run <task> [--harness claude-code|opencode] [--model claude-opus-5-5] [--task-tier 1] \
  [--stages <stage> ...] [--budget 2.0] [--max-duration 1h]
```

For example:

```bash
aura run dummy_task
aura run dataset_similarity --task-tier 2 --stages lit_review research_design
```

`--model` accepts any `model_name` in `litellm/config.yaml` and defaults to the first. `--task-tier` chooses the inputs the agent receives; `--stages` chooses the outputs it should produce. The stages are `research_questions`, `lit_review`, `research_design`, `experiments`, `analysis` and `report`. Omitting `--stages` requests all of them (end-to-end). Each stage's output is written to `results/<stage>.<ext>`, or to `results/<stage>/` if it has several files.

The task is passed to the agent inline in its prompt and also mounted read-only at `/task/TASK.md`, so the agent can reread it. Each run creates `runs/<timestamp>-<task>-<n>/` containing:

- `workspace/`: everything the agent wrote, copied out of the container when the run ends
- `task/TASK.md`: the task exactly as the agent received it
- `<timestamp>_...eval`: Inspect's log of the run: every model call, tool call, approval decision and result. View it with `inspect view --log-dir runs/<run>`
- `run_config.json`: image tag and options (including stages)
- `cost.json`: the run's key alias, budget, expiry and final spend in USD
- `warnings.txt`: only if the gateway couldn't block the key or report its spend

Each run gets a fresh gateway key, limited to the chosen model, `--budget` (USD) and `--max-duration` (in LiteLLM's format, e.g. `30m` or `2h`). If the run reaches either limit, the gateway refuses further model calls and the run ends with an error. The key is blocked when the run ends, however it ends, and its spend is recorded about 12 seconds later, once LiteLLM has saved it. Budgets can be overshot slightly, by whatever the run spends in the last few seconds before the limit is noticed.

Inside the container, the agent can read `/skills` and `/task` (read-only), write to `/workspace`, and `pip install` anything in the [PyPI mirror](#pypi-mirror).

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

### Literature tools

Every run gets the literature server's tools (Claude Code names them `mcp__literature__<tool>`, OpenCode `literature_<tool>`):

| Tool | Purpose |
|---|---|
| `search_papers` | Search Semantic Scholar by query, optionally filtered by year and venue |
| `get_paper` | Metadata and abstract for a paper (by Semantic Scholar id, `DOI:<doi>` or `ARXIV:<id>`) |
| `get_citations` | Papers citing a given paper |
| `get_fulltext_info` | Page count and figure/table captions with their pages, for papers with an open-access PDF |
| `read_pages` | Text of a range of pages (up to 10 per call) |
| `get_page_image` | One page as an image, for reading figures and plots |

Results are cached in `litmcp/cache/` (PDFs in `litmcp/cache/pdfs/`), so repeated questions get identical answers without calling Semantic Scholar again. Delete the folder to start fresh. Figure reading via `get_page_image` relies on the model being multimodal.

To see which literature tools an agent called, open the run in `inspect view` and filter its transcript by tool.

### Approval

Inspect checks every tool call the model proposes against `approval.yaml` before the harness sees it. Groups are tried in order and the first whose `tools` pattern matches decides; a pattern without `*` matches as a prefix. Patterns use each harness's own tool names (e.g. `Bash` and `mcp__literature__search_papers` for Claude Code, `bash` and `literature_search_papers` for OpenCode). A rejected call is never run: the model is told it was refused and proposes something else.

Every group currently uses the `auto` approver. To gate shell commands and file writes, change the last group's `name` to `human` (approve each call in Inspect's terminal display) or to a custom approver.

### PyPI mirror

The agent's `pip` installs from `pypiserver`, which serves only the wheels in `pypi/wheelhouse/`. `build_wheelhouse.sh` fills it by downloading every package in `pypi/allowlist.txt` with its dependencies, so those dependencies are installable too, and only at the downloaded versions. The wheels are built in the agent image so they match its Python version and CPU architecture; on Apple Silicon these are CPU-only Linux wheels.

### Making changes

If making changes to the sandbox, some files require extra changes being made elsewhere:

| If you've changed | Then |
|---|---|
| `agent/Dockerfile` or `agent/requirements.txt` | increment `AGENT_TAG` in `.env`, then run `./scripts/build.sh` and `./scripts/build_wheelhouse.sh` |
| `pypi/allowlist.txt` | run `./scripts/build_wheelhouse.sh`, then `docker compose restart pypiserver` |
| `approval.yaml` or `agent/compose.yaml` | nothing; the next `aura run` uses them |
| `litellm/config.yaml` | run `docker compose restart litellm`. If a provider rejects a request field Inspect sends, drop it for that model with `additional_drop_params` (see the Foundry models). If adding a provider, also add its key variable names to `litellm`'s `environment` in `docker-compose.yml` and run `docker compose up -d litellm` |
| Anything in `litmcp/` | run `./scripts/build.sh`, then `docker compose up -d litmcp` (add or change its dependencies in the `litmcp` group in `pyproject.toml`, then `uv sync`; pre-commit regenerates `litmcp/requirements.txt`) |
| Keys in `~/.zshrc` | run `source ~/.zshrc`, then `docker compose up -d litellm litmcp` |

### Rules

- The harnesses skip their own permission prompts (`inspect_swe` passes `--dangerously-skip-permissions`); the container and `approval.yaml` are what make that safe.
- Never mount the Docker socket, your home folder or `~/.claude` into the agent container.
- Never commit keys: store in global environment only.

### Verifying the sandbox

If needing to check the sandbox is still secure (e.g. after making changes), run the following from the repo root, with the shared services running. `sandbox` starts a throwaway agent container from `agent/compose.yaml`, as Inspect does:

```bash
export SAMPLE_METADATA_IMAGE="research-sandbox:$(grep '^AGENT_TAG=' .env | cut -d= -f2)"
export SAMPLE_METADATA_RUN_DIR="$TMPDIR/aura-check" && mkdir -p "$SAMPLE_METADATA_RUN_DIR/task"
sandbox() { docker compose -f agent/compose.yaml run --rm -T default "$@"; }

# 1. A real run works → finishes; cost.json shows a spend above 0
aura run dummy_task --model claude-haiku-4-5 --budget 0.05

# 2. Gateway not reachable → "Could not resolve host"
sandbox curl -sS --max-time 5 http://litellm:4000/health/liveliness

# 3. No route out (covers Foundry, Semantic Scholar, arXiv, ...) → resolve error or timeout
sandbox curl -sS --max-time 5 https://example.com

# 4. Allowlisted package installs from the mirror → downloads successfully
sandbox pip download seaborn -d /tmp/x

# 5. Package outside the wheelhouse → "No matching distribution found"
sandbox pip download flask -d /tmp/x

# 6. Task is read-only → "Read-only file system"
sandbox touch /task/test

# 7. No secrets inside a real run → 0 (run while an `aura run` is in progress)
docker exec "$(docker ps -q --filter name=inspect- | head -1)" env \
  | grep -c -F -e "$AZURE_FOUNDRY_API_KEY" -e "$LITELLM_MASTER_KEY" -e "${S2_API_KEY:?}"

# 8. Not root → uid=1000(agent)
sandbox id

# 9. Memory limit enforced → process killed or MemoryError
sandbox python -c "b = bytearray(20 * 1024**3)"

# 10. Fresh each run → first command succeeds; second says "No such file or directory"
sandbox touch /tmp/marker
sandbox ls /tmp/marker

# 11. Literature server reachable → a list of tool names (search_papers, get_paper, ...)
sandbox curl -s -X POST http://litmcp:8000/mcp \
  -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | grep -o '"name":"[a-z_]*"'

# 12. Database not reachable from the sandbox → socket.gaierror (name not resolved)
sandbox python -c "import socket; socket.create_connection(('postgres', 5432), timeout=5)"

# 13. A run key can't create keys → an error, not a new key
KEY=$(curl -s localhost:4000/key/generate -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
  -H 'Content-Type: application/json' -d '{"key_alias": "sandbox-check",
  "models": ["claude-haiku-4-5"], "max_budget": 0.01, "duration": "10m",
  "allowed_routes": ["llm_api_routes"]}' | jq -r .key)
curl -s localhost:4000/key/generate -H "Authorization: Bearer $KEY" \
  -H 'Content-Type: application/json' -d '{}'
curl -s localhost:4000/key/block -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
  -H 'Content-Type: application/json' -d "{\"key\": \"$KEY\"}" > /dev/null

# 14. Budget enforced → the run stops with a budget error; cost.json still records its spend
aura run dummy_task --budget 0.0001
```

Checks 2, 3 and 11 confirm that the agent reaches models only through Inspect's bridge and literature only through `litmcp`. Checks 7 and 12–14 confirm that agents never hold any key, can't reach the gateway's database, and are held to their run key's limits.

## License

Distributed under the terms of the [BSD license](LICENSE).
