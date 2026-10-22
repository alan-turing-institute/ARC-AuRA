"""
Run a task in the agent sandbox.

A run (`run`) goes through these steps:

1. Build the prompt from the task's files, tier and stages, and make the run folder
   `runs/<id>/`, holding `task/TASK.md` and `run_config.json`.
2. Build a one-sample Inspect task (`make_task`). Its sandbox is
   `agent/compose.yaml`, its solver the harness agent, and its approval policy
   `approval.yaml`.
3. Create a run key on LiteLLM, limited to one model, a budget and an expiry.
4. Run the eval (`run_eval`). Inspect starts a fresh agent container, and the
   harness's model calls come back to Inspect through the bridge. Inspect sends
   them on to LiteLLM with the run key and checks each tool call against the
   approval policy. Inspect writes the `.eval` log to the run folder.
5. When the sample ends, however it ends, copy `/workspace` into the run folder
   (`copy_workspace`). Inspect then deletes the container.
6. Block the run key and write its spend to `cost.json` (`_close_run_key`).
"""

import io
import json
import random
import sys
import tarfile
import time
from datetime import datetime
from pathlib import Path

from inspect_ai import Task, eval
from inspect_ai.agent import Agent
from inspect_ai.dataset import Sample
from inspect_ai.model import get_model
from inspect_ai.solver import TaskState
from inspect_ai.util import sandbox

from aura.constants import AGENT_COMPOSE, AGENT_TAG, APPROVAL_CONFIG, PROJECT_ROOT
from aura.gateway import GATEWAY_URL, block_key, create_run_key, get_spend
from aura.harnesses import HARNESSES
from aura.task import build_prompt

SPEND_WAIT = 12  # seconds: LiteLLM writes spend to its database every 10 s
WORKSPACE_TAR = "/tmp/workspace.tar.gz"


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


async def copy_workspace(state: TaskState) -> None:
    """
    Copy the sandbox's `/workspace` into the run folder's `workspace`.

    The archive is written by the agent, so extraction rejects paths and links that
    point outside the folder.

    Args:
        state: Sample state; its metadata holds the run folder.
    """
    await sandbox().exec(["tar", "-czf", WORKSPACE_TAR, "-C", "/workspace", "."])
    data = await sandbox().read_file(WORKSPACE_TAR, text=False)
    workspace = Path(state.metadata["run_dir"]) / "workspace"
    with tarfile.open(fileobj=io.BytesIO(data)) as tar:
        tar.extractall(workspace, filter="data")


def make_task(agent: Agent, prompt: str, run_dir: Path) -> Task:
    """
    Build a one-sample Inspect task that runs an agent in a fresh sandbox.

    Args:
        agent: Harness agent, from `HARNESSES`.
        prompt: Full task prompt.
        run_dir: Run folder; its `task` folder is mounted and `workspace` filled at
            the end.

    Returns:
        The task, with the approval policy and workspace copy attached.
    """
    metadata = {"image": f"research-sandbox:{AGENT_TAG}", "run_dir": str(run_dir)}
    return Task(
        dataset=[Sample(input=prompt, metadata=metadata)],
        solver=agent,
        sandbox=("docker", str(AGENT_COMPOSE)),
        approval=str(APPROVAL_CONFIG),
        cleanup=copy_workspace,
    )


def run_eval(task: Task, run_dir: Path, model: str, run_key: str) -> None:
    """
    Run a task with Inspect, calling the model through the gateway with the run key.

    Args:
        task: Task from `make_task`.
        run_dir: Run folder the `.eval` log is written to.
        model: Model name as configured in the LiteLLM gateway.
        run_key: Gateway key for the run's model calls; it never enters the sandbox.

    Raises:
        RuntimeError: If the eval doesn't finish successfully.
    """
    # LiteLLM forwards to Azure Foundry. The `azure/` service stops Inspect sending
    # options only Anthropic's own API accepts (e.g. thinking block binding).
    gateway_model = get_model(
        f"anthropic/azure/{model}", base_url=GATEWAY_URL, api_key=run_key
    )
    (log,) = eval(task, model=gateway_model, log_dir=str(run_dir))
    if log.status != "success":
        raise RuntimeError(
            f"Run {log.status}: {log.error.message if log.error else ''}"
        )


def _warn(run_dir: Path, message: str) -> None:
    """Print a warning and append it to the run's `warnings.txt`."""
    line = f"Warning: {message}\n"
    sys.stderr.write(line)
    with (run_dir / "warnings.txt").open("a") as log:
        log.write(line)


def _close_run_key(key: str, run_dir: Path, budget: float, max_duration: str) -> None:
    """
    Block a run's key and write what it spent to `cost.json`.

    Gateway failures only give a warning, so they can't hide an error from the run
    itself; the key's expiry still stops it being used.

    Args:
        key: The run's key, from `create_run_key`.
        run_dir: Run folder to write `cost.json` to.
        budget: The key's budget in USD, recorded alongside the spend.
        max_duration: The key's expiry, recorded alongside the spend.
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
        "duration": max_duration,
        "spend_usd": spend,
    }
    (run_dir / "cost.json").write_text(json.dumps(cost, indent=2))


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
    prompt = build_prompt(task, tier, stages)
    run_dir = make_run_dir(task)
    (run_dir / "task" / "TASK.md").write_text(prompt)
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
    (run_dir / "run_config.json").write_text(json.dumps(config, indent=2))
    eval_task = make_task(HARNESSES[harness](model), prompt, run_dir)
    metadata = {"task": task, "harness": harness, "tier": tier}
    key = create_run_key(run_dir.name, model, budget, max_duration, metadata)
    try:
        run_eval(eval_task, run_dir, model, key)
    finally:
        _close_run_key(key, run_dir, budget, max_duration)
    print(f"Finished: {run_dir}")
