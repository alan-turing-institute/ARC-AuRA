"""Run a task in the agent sandbox."""

import json
import os
import random
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from aura.constants import AGENT_TAG, PROJECT_ROOT
from aura.task import build_prompt


def claude_code_command(prompt: str, model: str) -> list[str]:
    """Build a headless Claude Code command."""
    return [
        "claude", "-p", prompt, "--model", model,
        "--output-format", "json", "--dangerously-skip-permissions",
    ]  # fmt: skip


HARNESSES = {"claude-code": claude_code_command}


def make_run_dir(task: str) -> Path:
    """Create a fresh run folder containing an empty workspace."""
    run_id = f"{datetime.now():%Y%m%d-%H%M%S}-{task}-{random.randrange(32768)}"
    run_dir = PROJECT_ROOT / "runs" / run_id
    (run_dir / "workspace").mkdir(parents=True)
    return run_dir


def compose_run(command: list[str], run_dir: Path) -> None:
    """Run a command in a fresh agent container, copying output to `log.txt`."""
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
    prompt = build_prompt(task, tier)
    command = HARNESSES[harness](prompt, model)
    run_dir = make_run_dir(task)
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
