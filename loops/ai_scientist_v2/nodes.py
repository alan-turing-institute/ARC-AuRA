"""Nodes of the search tree, and the journal that records them."""

import json
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class Node:
    """
    One attempt at the experiment: a complete script, and the results of running it.

    Attributes:
        id: Unique ID, also the name of the node's folder in `tree/`.
        stage: Search stage: initial_implementation, baseline_tuning,
            creative_research or ablation_studies.
        op: Operator that made it: draft, debug, improve, tune or ablate.
        parent_id: ID of the node it was made from; None for a draft.
        plan: The model's plan for the code.
        code: The experiment script.
        output: End of the script's stdout and stderr.
        exit_code: The script's exit code; None if it timed out.
        timed_out: Whether the script hit the timeout.
        metric: The idea's metric, from `metrics.json`.
        is_bug: Whether the node is buggy, from the run and the review; None if
            its review didn't finish, e.g. because the budget ran out.
        summary: The review's summary: the bug and a fix, or the main findings.
        plot_feedback: The model's feedback on the node's plots.
        debug_depth: Debug steps in a row that led to this node.
    """

    id: str
    stage: str
    op: str
    parent_id: str | None
    plan: str
    code: str
    output: str = ""
    exit_code: int | None = None
    timed_out: bool = False
    metric: float | None = None
    is_bug: bool | None = None
    summary: str = ""
    plot_feedback: str | None = None
    debug_depth: int = 0


def save_journal(nodes: list[Node], path: Path) -> None:
    """Write all nodes to a JSON journal."""
    path.write_text(json.dumps([asdict(node) for node in nodes], indent=2))


def save_bests(bests: dict[str, Node], path: Path) -> None:
    """Write each stage's best node's ID, folder, metric and summary to JSON."""
    summary = {
        stage: {
            "id": n.id,
            "folder": f"tree/{n.id}",
            "metric": n.metric,
            "summary": n.summary,
        }
        for stage, n in bests.items()
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary, indent=2))


def emit(event: str, **fields) -> None:
    """Print one JSON event line to stdout, which the launcher saves in `log.txt`."""
    print(json.dumps({"type": event, **fields}), flush=True)


def summarise_journal(nodes: list[Node], limit: int = 10) -> str:
    """One line per recent node: id, operator, metric or "buggy", and summary."""
    return "\n".join(
        f"{n.id} ({n.op}): {'buggy' if n.is_bug else n.metric} - {n.summary}"
        for n in nodes[-limit:]
    )
