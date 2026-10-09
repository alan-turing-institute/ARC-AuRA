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

Agents run in throwaway Docker containers with no internet access. Each run gets a fresh container, which is deleted when the run finishes. API keys never enter the container or the repo.

### Components

| Component | Config | Role |
|---|---|---|
| `agent` | `agent/Dockerfile` | Image the harness runs in (Claude Code + Python stack). One fresh container per run; sandbox network only. |
| `litellm` | `litellm/config.yaml` | Model gateway. Holds API keys and forwards model calls; agents only get a gateway key. |
| `proxy` | `proxy/squid.conf` | Manages agent website access. |
| `litmcp` | `litmcp/` | Literature MCP server. Searches Semantic Scholar and serves open-access paper text and page images to agents, caching every result in `litmcp/cache/`. Holds the Semantic Scholar key; agents only reach it over the sandbox network. |
| `mcp.json` | repo root | MCP config pointing the agent at `litmcp`. `aura run` passes it to Claude Code with `--mcp-config`. |
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

3. Build the docker images (the agent and litmcp):

```bash
./scripts/build.sh
```

### Each session

1. If not already started, startup colima:

```bash
colima start
```

2. Startup the modelgateway and proxy and verify they are running. If using Colima, start it first with `colima start` (skip this if it is already running; check with `colima status`).

```bash
docker compose up -d litellm proxy litmcp   # start gateway, proxy and literature server
docker compose ps                           # all three should be running
```

3. Once finished for the day, shut everything down aferwards with:

```bash
docker compose down
```

4. Stop the colima VM to free up its CPU and memory (it keeps running, even through sleep, until stopped):

```bash
colima stop
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
- `log.txt`: full output, with one JSON event per line for each agent step (tool calls, results, final summary)
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

### Literature tools

Every run gets the literature server's tools (Claude Code names them `mcp__literature__<tool>`):

| Tool | Purpose |
|---|---|
| `search_papers` | Search Semantic Scholar by query, optionally filtered by year and venue |
| `get_paper` | Metadata and abstract for a paper (by Semantic Scholar id, `DOI:<doi>` or `ARXIV:<id>`) |
| `get_citations` | Papers citing a given paper |
| `get_fulltext_info` | Page count and figure/table captions with their pages, for papers with an open-access PDF |
| `read_pages` | Text of a range of pages (up to 10 per call) |
| `get_page_image` | One page as an image, for reading figures and plots |

Results are cached in `litmcp/cache/` (PDFs in `litmcp/cache/pdfs/`), so repeated questions get identical answers without calling Semantic Scholar again. Delete the folder to start fresh. Figure reading via `get_page_image` relies on the model being multimodal.

To see which literature tools an agent called:

```bash
grep -o 'mcp__literature__[a-z_]*' runs/<run>/log.txt | sort | uniq -c
```

### Making changes

If making changes to the sandbox, some files require extra changes being made elsewhere:

| If you've changed | Then |
|---|---|
| `agent/Dockerfile` or `agent/requirements.txt` | increment `AGENT_TAG` in `.env`, then run `./scripts/build.sh` |
| `litellm/config.yaml` | run `docker compose restart litellm` |
| Anything in `litmcp/` | run `./scripts/build.sh`, then `docker compose up -d litmcp` (and `uv sync` if `litmcp/requirements.txt` changed; keep it in step with the `litmcp` group in `pyproject.toml`) |
| Keys in `~/.zshrc` | run `source ~/.zshrc`, then `docker compose up -d litellm litmcp` |

### Rules

- Only use `--dangerously-skip-permissions` (in `aura run`) inside the sandbox; the container is what makes it safe.
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

# 12. Literature server reachable → a list of tool names (search_papers, get_paper, ...)
RUN_DIR="$TMPDIR" docker compose run --rm -T agent curl -s -X POST http://litmcp:8000/mcp \
  -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | grep -o '"name":"[a-z_]*"'

# 13. Semantic Scholar not reachable directly → "Could not resolve host" or timeout
RUN_DIR="$TMPDIR" docker compose run --rm -T agent curl -sS --noproxy '*' --max-time 5 https://api.semanticscholar.org

# 14. arXiv not reachable via proxy → "CONNECT tunnel failed, response 403"
RUN_DIR="$TMPDIR" docker compose run --rm -T agent curl -sS -o /dev/null https://arxiv.org

# 15. Semantic Scholar key not inside → 0
RUN_KEY="$LITELLM_MASTER_KEY" RUN_DIR="$TMPDIR" docker compose run --rm -T agent env \
  | grep -c -F -e "${S2_API_KEY:?set S2_API_KEY first}"
```

Checks 12–14 confirm that agents get literature only through `litmcp`, not directly from the internet.

## License

Distributed under the terms of the [BSD license](LICENSE).
