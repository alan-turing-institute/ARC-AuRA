"""Run a task in the agent sandbox."""

import json
import os
import random
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from aura.constants import AGENT_TAG, PROJECT_ROOT
from aura.gateway import block_key, create_run_key, get_spend
from aura.harnesses import HARNESSES
from aura.task import build_prompt

SPEND_WAIT = 12  # seconds: LiteLLM writes spend to its database every 10 s


def make_run_dir(task: str) -> Path:
    """
    Create a fresh run folder with empty `workspace` and `task` folders.

    Args:
        task: Name of the task, used in the run ID.

    Returns:
        Path to `runs/<timestamp>-<task>-<n>/`.
    """
    run_id = f"{datetime.now():%Y%m%d-%H%M%S}-{task}-{random.randrange(32768)}"
    run_dir = PROJECT_ROOT / "runs" / run_id
    for name in ("workspace", "task"):
        (run_dir / name).mkdir(parents=True)
    return run_dir


def compose_run(command: list[str], run_dir: Path, run_key: str) -> None:
    """
    Run a command in a fresh agent container, copying output to `log.txt`.

    Args:
        command: Harness command to run inside the container.
        run_dir: Run folder whose `workspace` and `task` folders are mounted.
        run_key: Gateway key the agent uses for model calls, passed as `RUN_KEY`.

    Raises:
        subprocess.CalledProcessError: If the container exits with an error.
    """
    env = {**os.environ, "RUN_DIR": str(run_dir), "RUN_KEY": run_key}
    compose_file = str(PROJECT_ROOT / "docker-compose.yml")
    docker = ["docker", "compose", "-f", compose_file, "run", "--rm", "-T", "agent"]
    with (
        subprocess.Popen(
            [*docker, *command],
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        ) as proc,
        (run_dir / "log.txt").open("w") as log,
    ):
        for line in proc.stdout or []:
            sys.stdout.write(line)
            log.write(line)
    if proc.returncode:
        raise subprocess.CalledProcessError(proc.returncode, proc.args)


def _warn(run_dir: Path, message: str) -> None:
    """Print a warning and append it to the run's `log.txt`."""
    line = f"Warning: {message}\n"
    sys.stderr.write(line)
    with (run_dir / "log.txt").open("a") as log:
        log.write(line)


def _close_run_key(key: str, run_dir: Path, budget: float, duration: str) -> None:
    """
    Block a run's key and write what it spent to `cost.json`.

    Gateway failures only give a warning, so they can't hide an error from the run
    itself; the key's expiry still stops it being used.

    Args:
        key: The run's key, from `create_run_key`.
        run_dir: Run folder to write `cost.json` to.
        budget: The key's budget in USD, recorded alongside the spend.
        duration: The key's expiry, recorded alongside the spend.
    """
    try:
        block_key(key)
    except RuntimeError as e:
        _warn(run_dir, f"couldn't block the run's key: {e}")
    try:
        time.sleep(SPEND_WAIT)  # let LiteLLM write the run's last spend
        spend = get_spend(key)
    except RuntimeError as e:
        _warn(run_dir, f"couldn't read the run's spend: {e}")
        return
    cost = {
        "key_alias": f"run-{run_dir.name}",
        "max_budget": budget,
        "duration": duration,
        "spend_usd": spend,
    }
    (run_dir / "cost.json").write_text(json.dumps(cost, indent=2))


def run(
    task: str,
    harness: str,
    model: str,
    tier: int,
    budget: float,
    duration: str,
) -> None:
    """
    Build a task prompt, record the run's settings and run it in the sandbox.

    Args:
        task: Name of a folder in `tasks/`.
        harness: Key of `HARNESSES` naming the agent harness.
        model: Model name as configured in the LiteLLM gateway.
        tier: Number of task sections to include, in order.
        budget: Maximum spend on model calls for the run, in USD.
        duration: How long the run's key is valid, in LiteLLM's format, e.g. "1h".
    """
    prompt = build_prompt(task, tier)
    command = HARNESSES[harness](prompt, model)
    run_dir = make_run_dir(task)
    (run_dir / "task" / "TASK.md").write_text(prompt)
    config = {
        "image": f"research-sandbox:{AGENT_TAG}",
        "task": task,
        "task_tier": tier,
        "harness": harness,
        "model": model,
        "budget": budget,
        "duration": duration,
        "command": command,
    }
    (run_dir / "run_config.json").write_text(json.dumps(config, indent=2))
    metadata = {"task": task, "harness": harness, "tier": tier}
    key = create_run_key(run_dir.name, model, budget, duration, metadata)
    try:
        compose_run(command, run_dir, key)
    finally:
        _close_run_key(key, run_dir, budget, duration)
    print(f"Finished: {run_dir}")
