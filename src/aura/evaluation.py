"""Run a harness as a one-sample Inspect eval in a fresh agent container."""

import io
import tarfile
from pathlib import Path

from inspect_ai import Task, eval
from inspect_ai.agent import Agent
from inspect_ai.dataset import Sample
from inspect_ai.model import get_model
from inspect_ai.solver import TaskState
from inspect_ai.util import sandbox

from aura.constants import AGENT_COMPOSE, AGENT_TAG, APPROVAL_CONFIG
from aura.gateway import GATEWAY_URL

WORKSPACE_TAR = "/tmp/workspace.tar.gz"


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


def make_inspect_task(agent: Agent, prompt: str, run_dir: Path) -> Task:
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


def run_inspect_eval(task: Task, run_dir: Path, model: str, run_key: str) -> None:
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
    gateway_model = get_model(
        f"anthropic/{model}", base_url=GATEWAY_URL, api_key=run_key
    )
    (log,) = eval(task, model=gateway_model, log_dir=str(run_dir))
    if log.status != "success":
        raise RuntimeError(
            f"Run {log.status}: {log.error.message if log.error else ''}"
        )
