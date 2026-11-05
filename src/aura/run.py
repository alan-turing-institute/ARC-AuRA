"""Run a task in the agent sandbox."""

import json
import random
from datetime import datetime
from pathlib import Path

from aura.constants import AGENT_TAG, PROJECT_ROOT
from aura.gateway import run_key
from aura.harnesses import HARNESSES
from aura.monitor import monitor
from aura.sandbox import build_task, run_in_sandbox
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
    monitor_model: str,
    tier: int,
    stages: list[str],
    budget: float,
    max_duration: str,
    human_review: bool,
    history_size: int,
    escalate_at: int,
    reject_at: int,
) -> None:
    """
    Build a task prompt, record the run's settings and run it in the sandbox.

    Args:
        task: Name of a folder in `tasks/`.
        harness: Key of `HARNESSES` naming the agent harness.
        model: Agent's model name as configured in the LiteLLM gateway.
        monitor_model: Monitor's model name as configured in the LiteLLM gateway.
        tier: Number of task sections to include, in order.
        stages: Names from `STAGES` to produce outputs for.
        budget: Maximum spend on model calls for the run, in USD.
        max_duration: How long the run's key is valid, in LiteLLM's format, e.g. "1h".
        human_review: Whether a human decides on calls the monitor escalates.
        history_size: Number of recent messages the monitor sees.
        escalate_at: Lowest suspicion score the monitor escalates.
        reject_at: Lowest suspicion score the monitor rejects.
    """
    config = {
        "image": f"research-sandbox:{AGENT_TAG}",
        "task": task,
        "task_tier": tier,
        "stages": stages,
        "harness": harness,
        "model": model,
        "monitor_model": monitor_model,
        "human_review": human_review,
        "monitor_history_size": history_size,
        "escalate_at": escalate_at,
        "reject_at": reject_at,
        "budget": budget,
        "duration": max_duration,
    }
    metadata = {"task": task, "harness": harness, "tier": tier}

    task_monitor = monitor(history_size, escalate_at, reject_at)
    prompt = build_prompt(task, tier, stages)
    run_dir = make_run_dir(task, prompt, config)
    agent = HARNESSES[harness](model)
    task_spec = build_task(agent, task_monitor, prompt, run_dir, human_review)
    models = [model, monitor_model]
    with run_key(run_dir, models, budget, max_duration, metadata) as key:
        run_in_sandbox(task_spec, run_dir, model, monitor_model, key)
    print(f"Finished: {run_dir}")
