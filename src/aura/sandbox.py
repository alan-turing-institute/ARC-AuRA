"""Run a harness agent in a fresh sandbox, through Inspect."""

import io
import tarfile
from pathlib import Path

from inspect_ai import Task, eval
from inspect_ai.agent import Agent
from inspect_ai.approval import (
    ApprovalPolicy,
    Approver,
    human_approver,
    read_approval_policies,
)
from inspect_ai.dataset import Sample
from inspect_ai.model import Model, get_model
from inspect_ai.solver import TaskState
from inspect_ai.util import sandbox

from aura.constants import AGENT_COMPOSE, AGENT_TAG, APPROVAL_CONFIG
from aura.gateway import GATEWAY_URL
from aura.monitor import monitor_summary

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

    def workspace_filter(
        member: tarfile.TarInfo, destination: str
    ) -> tarfile.TarInfo | None:
        """
        Apply tarfile's "data" filter, skipping links it rejects instead of failing.

        A rejected link, such as a virtual environment's absolute `bin/python`
        symlink, would otherwise abort extraction and lose the files after it.

        Args:
            member: Archive member about to be extracted.
            destination: Folder the archive is extracted into.

        Returns:
            The member as the data filter allows it, or None to skip it.
        """
        try:
            return tarfile.data_filter(member, destination)
        except (tarfile.AbsoluteLinkError, tarfile.LinkOutsideDestinationError):
            return None

    with tarfile.open(fileobj=io.BytesIO(data)) as tar:
        tar.extractall(workspace, filter=workspace_filter)


def approval_policies(monitor: Approver, human_review: bool) -> list[ApprovalPolicy]:
    """
    Load `approval.yaml`, then add the monitor and, if asked for, a human approver.

    Without the human approver, calls escalated past every approver are denied.

    Args:
        monitor: Approver for every call `approval.yaml` doesn't decide.
        human_review: Whether a human decides on escalated calls.

    Returns:
        The approval chain.
    """
    policies = read_approval_policies(str(APPROVAL_CONFIG))
    human = [ApprovalPolicy(human_approver(), "*")] if human_review else []
    return [*policies, ApprovalPolicy(monitor, "*"), *human]


def build_task(
    agent: Agent, monitor: Approver, prompt: str, run_dir: Path, human_review: bool
) -> Task:
    """
    Build the one-sample Inspect task that runs an agent in a fresh sandbox.

    Args:
        agent: Harness agent, from `HARNESSES`.
        monitor: Approver for every call `approval.yaml` doesn't decide.
        prompt: Full task prompt.
        run_dir: Run folder; its `task` folder is mounted and `workspace` filled at
            the end.
        human_review: Whether a human decides on calls the monitor escalates.

    Returns:
        The task, with the approval chain, monitor summary and workspace copy
        attached.
    """
    metadata = {"image": f"research-sandbox:{AGENT_TAG}", "run_dir": str(run_dir)}
    return Task(
        dataset=[Sample(input=prompt, metadata=metadata)],
        solver=agent,
        scorer=monitor_summary(),
        sandbox=("docker", str(AGENT_COMPOSE)),
        approval=approval_policies(monitor, human_review),
        cleanup=copy_workspace,
    )


def gateway_model(model: str, run_key: str) -> Model:
    """Return an Inspect model that calls `model` through the gateway."""
    return get_model(f"anthropic/{model}", base_url=GATEWAY_URL, api_key=run_key)


def run_in_sandbox(
    task: Task, run_dir: Path, model: str, monitor_model: str, run_key: str
) -> None:
    """
    Run a task's agent in its sandbox, calling models through the gateway.

    Args:
        task: Task from `build_task`.
        run_dir: Run folder the `.eval` log is written to.
        model: Agent's model name as configured in the LiteLLM gateway.
        monitor_model: Monitor's model name as configured in the LiteLLM gateway.
        run_key: Gateway key for the run's model calls; it never enters the sandbox.

    Raises:
        RuntimeError: If the run doesn't finish successfully.
    """
    (log,) = eval(
        task,
        model=gateway_model(model, run_key),
        model_roles={"monitor": gateway_model(monitor_model, run_key)},
        log_dir=str(run_dir),
    )
    if log.status != "success":
        raise RuntimeError(
            f"Run {log.status}: {log.error.message if log.error else ''}"
        )
