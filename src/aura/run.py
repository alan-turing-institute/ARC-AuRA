"""Run a task in the agent sandbox."""

import json
import os
import random
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from aura.constants import AGENT_TAG, PROJECT_ROOT
from aura.harnesses import HARNESSES
from aura.task import build_prompt


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


def compose_run(command: list[str], run_dir: Path) -> None:
    """
    Run a command in a fresh agent container, copying output to `log.txt`.

    Args:
        command: Harness command to run inside the container.
        run_dir: Run folder whose `workspace` and `task` folders are mounted.

    Raises:
        subprocess.CalledProcessError: If the container exits with an error.
    """
    env = {
        **os.environ,
        "RUN_DIR": str(run_dir),
        "RUN_KEY": os.environ["LITELLM_MASTER_KEY"],  # TODO: stop passing master key
    }
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


def run(task: str, harness: str, model: str, tier: int) -> None:
    """
    Build a task prompt, record the run's settings and run it in the sandbox.

    Args:
        task: Name of a folder in `tasks/`.
        harness: Key of `HARNESSES` naming the agent harness.
        model: Model name as configured in the LiteLLM gateway.
        tier: Number of task sections to include, in order.
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
        "command": command,
    }
    (run_dir / "run_config.json").write_text(json.dumps(config, indent=2))
    compose_run(command, run_dir)
    print(f"Finished: {run_dir}")
