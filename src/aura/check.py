"""
Verify the agent sandbox is secure.

Each check is a function returning whether it passed. To add or remove one, add or
remove its function and its line in `CHECKS` (or `RUN_CHECKS`, for checks that do a
real run).
"""

import json
import os
import subprocess
import tempfile
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from aura import gateway
from aura.constants import AGENT_COMPOSE, AGENT_TAG, PROJECT_ROOT

RUNS_DIR = PROJECT_ROOT / "runs"
CHECK_MODEL = "claude-haiku-4-5"
SECRET_VARS = ("AZURE_FOUNDRY_API_KEY", "LITELLM_MASTER_KEY", "S2_API_KEY")
LITMCP_TOOLS_LIST = '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
STATUS = {True: "\033[32mPASS\033[0m", False: "\033[31mFAIL\033[0m"}  # green, red


def sandbox(*cmd: str) -> subprocess.CompletedProcess[str]:
    """Run a command in a throwaway agent container, started as Inspect starts one."""
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
    """Return a command's stdout and stderr together."""
    return result.stdout + result.stderr


def aura_run(budget: str) -> tuple[subprocess.CompletedProcess[str], Path]:
    """
    Do a real `aura run` of `dummy_task` with a given budget.

    Args:
        budget: Maximum spend for the run, in USD.

    Returns:
        The finished command, and the `cost.json` path in the run folder it created.
    """
    before = set(RUNS_DIR.glob("*"))
    cmd = ["aura", "run", "dummy_task", "--model", CHECK_MODEL, "--budget", budget]
    result = subprocess.run(cmd, capture_output=True, text=True)
    (run_dir,) = set(RUNS_DIR.glob("*")) - before
    return result, run_dir / "cost.json"


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
    secrets = [value for var in SECRET_VARS if (value := os.environ.get(var))]
    env = sandbox("env").stdout
    return not any(secret in env for secret in secrets)


def not_root() -> bool:
    """Check the sandbox runs as the unprivileged `agent` user."""
    return "uid=1000(agent)" in sandbox("id").stdout


def memory_limited() -> bool:
    """Allocate more memory than the container's limit; it should fail."""
    return sandbox("python", "-c", "b = bytearray(20 * 1024**3)").returncode != 0


def fresh_containers() -> bool:
    """Write a file in one container; it shouldn't exist in the next."""
    written = sandbox("touch", "/tmp/marker").returncode == 0
    return written and sandbox("ls", "/tmp/marker").returncode != 0


def litmcp_reachable() -> bool:
    """List the literature server's tools from the sandbox."""
    result = sandbox(
        "curl", "-s", "-X", "POST", "http://litmcp:8000/mcp",
        "-H", "Content-Type: application/json",
        "-H", "Accept: application/json, text/event-stream",
        "-d", LITMCP_TOOLS_LIST,
    )  # fmt: skip
    return "search_papers" in result.stdout


def database_unreachable() -> bool:
    """Connect to the gateway's database from the sandbox; its name shouldn't resolve."""
    code = "import socket; socket.create_connection(('postgres', 5432), timeout=5)"
    return "gaierror" in output(sandbox("python", "-c", code))


def run_key_limited() -> bool:
    """Create a key with a run key; the gateway should refuse."""
    alias = f"sandbox-check-{datetime.now():%Y%m%d-%H%M%S}"  # aliases must be unique
    key = gateway.create_run_key(alias, [CHECK_MODEL], 0.01, "10m", {})
    try:
        headers = {"Authorization": f"Bearer {key}"}
        response = gateway.client.post("/key/generate", headers=headers, json={})
        return not response.is_success
    finally:
        gateway.block_key(key)


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


def report(description: str, check: Callable[[], bool], width: int) -> bool:
    """
    Run one check and print its description, dotted out to a green PASS or red FAIL.

    An error counts as a failure and is printed after FAIL, so the remaining checks
    still run.

    Args:
        description: What the check confirms.
        check: Function returning whether the check passed.
        width: Length of the longest description, so every PASS/FAIL lines up.

    Returns:
        Whether the check passed.
    """
    try:
        passed, error = check(), ""
    except Exception as e:
        passed, error = False, f"  {e}"
    leader = f"{description} ".ljust(width + 4, ".")
    print(f"{leader} {STATUS[passed]}{error}", flush=True)
    return passed


def check(runs: bool) -> bool:
    """
    Run every sandbox check, printing each result.

    Args:
        runs: Whether to also run `RUN_CHECKS`, which do real (paid) runs.

    Returns:
        Whether every check passed.
    """
    checks = {**CHECKS, **RUN_CHECKS} if runs else CHECKS
    width = max(map(len, checks))
    results = [report(description, fn, width) for description, fn in checks.items()]
    return all(results)  # after running every check, not stopping at a failure
