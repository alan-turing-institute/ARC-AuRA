"""
Sandbox security checks, run by `aura check`.

Each check is a function returning whether it passed. To add or remove one, add or
remove its function and its line in `CHECKS` (or `RUN_CHECKS`, for checks that do a
real run).
"""

import json
import os
import re
import subprocess
import tempfile
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from aura import gateway
from aura.constants import AGENT_COMPOSE, AGENT_TAG

CHECK_MODEL = "claude-haiku-4-5"


def sandbox(*cmd: str) -> subprocess.CompletedProcess[str]:
    """
    Run a command in a throwaway agent container, started as Inspect starts one.

    The container comes from `docker compose run --rm -T default <cmd>` on
    `agent/compose.yaml`, with an empty `task` folder mounted.

    Args:
        cmd: The command and its arguments, e.g. `"id"` or `"touch", "/task/test"`.

    Returns:
        The finished `docker compose run`, with its output captured as text.
    """
    with tempfile.TemporaryDirectory() as run_dir:
        (Path(run_dir) / "task").mkdir()
        env = {
            **os.environ,
            "SAMPLE_METADATA_IMAGE": f"research-sandbox:{AGENT_TAG}",
            "SAMPLE_METADATA_RUN_DIR": run_dir,
        }
        compose = ["docker", "compose", "-f", str(AGENT_COMPOSE), "run", "--rm", "-T"]
        return subprocess.run(
            [*compose, "default", *cmd], env=env, capture_output=True, text=True
        )


def output(result: subprocess.CompletedProcess[str]) -> str:
    """
    Return a command's stdout and stderr together.

    Args:
        result: A finished command, run with its output captured as text.

    Returns:
        Its stdout followed by its stderr.
    """
    return result.stdout + result.stderr


def aura_run(budget: str) -> tuple[subprocess.CompletedProcess[str], Path]:
    """
    Do a real `aura run` of `dummy_task` with a given budget.

    Args:
        budget: Maximum spend for the run, in USD.

    Returns:
        The finished command, and the `cost.json` path in the run folder it created.

    Raises:
        RuntimeError: If the run stopped before creating its run folder.
    """
    cmd = ["aura", "run", "dummy_task", "--model", CHECK_MODEL, "--budget", budget]
    result = subprocess.run(cmd, capture_output=True, text=True)
    match = re.search(r"^Run folder: (.+)$", result.stdout, re.MULTILINE)
    if not match:
        raise RuntimeError("aura run stopped before creating its run folder")
    return result, Path(match[1]) / "cost.json"


def gateway_unreachable() -> bool:
    """Curl the gateway from the sandbox; its name shouldn't resolve."""
    url = "http://litellm:4000/health/liveliness"
    result = sandbox("curl", "-sS", "--max-time", "5", url)
    return "Could not resolve host" in output(result)


def no_internet() -> bool:
    """Curl an external site from the sandbox; it should fail."""
    result = sandbox("curl", "-sS", "--max-time", "5", "https://example.com")
    return result.returncode != 0


def mirror_serves_allowlist() -> bool:
    """Download an allowlisted package from the mirror."""
    return sandbox("pip", "download", "seaborn", "-d", "/tmp/x").returncode == 0


def mirror_blocks_others() -> bool:
    """Download a package outside the wheelhouse; the mirror shouldn't have it."""
    result = sandbox("pip", "download", "flask", "-d", "/tmp/x")
    return "No matching distribution found" in output(result)


def task_read_only() -> bool:
    """Write to `/task`; it should be a read-only mount."""
    return "Read-only file system" in output(sandbox("touch", "/task/test"))


def no_secrets() -> bool:
    """Look for the host's key values in the sandbox's environment."""
    secret_vars = ("AZURE_FOUNDRY_API_KEY", "LITELLM_MASTER_KEY", "S2_API_KEY")
    secrets = [value for var in secret_vars if (value := os.environ.get(var))]
    result = sandbox("env")
    if result.returncode != 0:  # empty output would otherwise pass
        return False
    return not any(secret in result.stdout for secret in secrets)


def not_root() -> bool:
    """Check the sandbox runs as the unprivileged `agent` user."""
    return "uid=1000(agent)" in sandbox("id").stdout


def memory_limited() -> bool:
    """
    Allocate past the container's memory limit; the limit itself should stop it.

    Reading the limit first means an unlimited container is never asked to allocate.
    The cgroup's `oom` count rises only when its own limit is hit, unlike `oom_kill`,
    which also counts host-level kills, so it's read in the allocating container.
    """
    cgroup = "/sys/fs/cgroup"  # the container's own cgroup (v2)
    limit = sandbox("cat", f"{cgroup}/memory.max").stdout.strip()
    if not limit.isdigit():  # "max", i.e. no limit
        return False
    allocate = f"python -c 'bytearray({limit} + 2**30)'"
    result = sandbox("sh", "-c", f"{allocate}; cat {cgroup}/memory.events")
    events = dict(line.split() for line in result.stdout.splitlines())
    return int(events["oom"]) > 0


def fresh_containers() -> bool:
    """Write a file in one container; it shouldn't exist in the next."""
    written = sandbox("touch", "/tmp/marker").returncode == 0
    return written and sandbox("ls", "/tmp/marker").returncode != 0


def litmcp_reachable() -> bool:
    """List the literature server's tools from the sandbox."""
    tools_list = '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
    result = sandbox(
        "curl", "-s", "--max-time", "5", "-X", "POST", "http://litmcp:8000/mcp",
        "-H", "Content-Type: application/json",
        "-H", "Accept: application/json, text/event-stream",
        "-d", tools_list,
    )  # fmt: skip
    return "search_papers" in result.stdout


def database_unreachable() -> bool:
    """Connect to the gateway's database from the sandbox; its name shouldn't resolve."""
    code = "import socket; socket.create_connection(('postgres', 5432), timeout=5)"
    return "gaierror" in output(sandbox("python", "-c", code))


def run_key_limited() -> bool:
    """
    Create a key with a run key; the gateway should refuse it as unauthorised.

    Raises:
        RuntimeError: If the gateway errors for another reason, so permission wasn't
            tested.
    """
    alias = f"sandbox-check-{datetime.now():%Y%m%d-%H%M%S}"  # aliases must be unique
    key = gateway.create_run_key(alias, [CHECK_MODEL], 0.01, "10m", {})
    try:
        headers = {"Authorization": f"Bearer {key}"}
        response = gateway.client.post("/key/generate", headers=headers, json={})
    finally:
        gateway.block_key(key)
    denied = response.status_code in (401, 403)
    if not denied and not response.is_success:
        raise RuntimeError(f"/key/generate failed ({response.status_code}), not denied")
    return denied


def run_billed() -> bool:
    """Do a real run; it should finish and record a spend above 0."""
    result, cost = aura_run("0.05")
    if result.returncode != 0:
        return False
    return json.loads(cost.read_text())["spend_usd"] > 0


def budget_enforced() -> bool:
    """Do a run with a tiny budget; it should stop with a budget error, spend recorded."""
    result, cost = aura_run("0.0001")
    stopped = result.returncode != 0 and "budget" in result.stderr.lower()
    return stopped and cost.exists()


CHECKS: dict[str, Callable[[], bool]] = {
    "Gateway unreachable from sandbox": gateway_unreachable,
    "No internet access": no_internet,
    "Allowlisted packages install": mirror_serves_allowlist,
    "Other packages blocked": mirror_blocks_others,
    "Task folder read-only": task_read_only,
    "No secrets in sandbox": no_secrets,
    "Agent not root": not_root,
    "Memory limit enforced": memory_limited,
    "Containers fresh each run": fresh_containers,
    "Literature server reachable": litmcp_reachable,
    "Database unreachable from sandbox": database_unreachable,
    "Run keys can't create keys": run_key_limited,
}
RUN_CHECKS: dict[str, Callable[[], bool]] = {
    "Real run completes and is billed": run_billed,
    "Budget enforced": budget_enforced,
}
