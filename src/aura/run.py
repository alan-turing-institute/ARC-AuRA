"""Run a task in the agent sandbox."""

import json
import random
from datetime import datetime
from pathlib import Path

from aura.constants import AGENT_TAG, PROJECT_ROOT
from aura.evaluation import make_inspect_task, run_inspect_eval
from aura.gateway import run_key
from aura.harnesses import HARNESSES
from aura.task import build_prompt


def make_run_dir(task: str, prompt: str, config: dict) -> Path:
    """
    Create a fresh run folder holding the task prompt and the run's settings.

    Args:
        task: Name of the task, used in the run ID.
        prompt: Full task prompt, written to `task/TASK.md`.
        config: Run settings, written to `run_config.json`.

    Returns:
        Path to `runs/<timestamp>-<task>-<n>/`, with an empty `workspace` folder.
    """
    run_id = f"{datetime.now():%Y%m%d-%H%M%S}-{task}-{random.randrange(32768)}"
    run_dir = PROJECT_ROOT / "runs" / run_id
    for name in ("workspace", "task"):
        (run_dir / name).mkdir(parents=True)
    (run_dir / "task" / "TASK.md").write_text(prompt)
    (run_dir / "run_config.json").write_text(json.dumps(config, indent=2))
    return run_dir


def run(
    task: str,
    harness: str,
    model: str,
    tier: int,
    stages: list[str],
    budget: float,
    max_duration: str,
) -> None:
    """
    Build a task prompt, record the run's settings and run it in the sandbox.

    Args:
        task: Name of a folder in `tasks/`.
        harness: Key of `HARNESSES` naming the agent harness.
        model: Model name as configured in the LiteLLM gateway.
        tier: Number of task sections to include, in order.
        stages: Names from `STAGES` to produce outputs for.
        budget: Maximum spend on model calls for the run, in USD.
        max_duration: How long the run's key is valid, in LiteLLM's format, e.g. "1h".
    """
    config = {
        "image": f"research-sandbox:{AGENT_TAG}",
        "task": task,
        "task_tier": tier,
        "stages": stages,
        "harness": harness,
        "model": model,
        "budget": budget,
        "duration": max_duration,
    }
    metadata = {"task": task, "harness": harness, "tier": tier}

    prompt = build_prompt(task, tier, stages)
    run_dir = make_run_dir(task, prompt, config)
    inspect_task = make_inspect_task(HARNESSES[harness](model), prompt, run_dir)
    with run_key(run_dir, model, budget, max_duration, metadata) as key:
        run_inspect_eval(inspect_task, run_dir, model, key)
    print(f"Finished: {run_dir}")
