"""
Run a node's code and review its output and plots.

Adapted from AI Scientist-v2's `ai_scientist/treesearch/parallel_agent.py`
(`parse_exec_result`, `_analyze_plots_with_vlm`); see LICENSE.
"""

import json
import math
import subprocess
import sys
from pathlib import Path

from ai_scientist_v2 import prompts, tools
from ai_scientist_v2.llm import call_tool, image_contents
from ai_scientist_v2.nodes import Node

_MAX_OUTPUT = 5000  # characters of output kept, from the end, as upstream does
_MAX_PLOTS = 10


def _run_script(
    code: str, node_dir: Path, timeout: int
) -> tuple[str, int | None, bool]:
    """
    Write code to `runfile.py` in a node's folder and run it there with a timeout.

    Args:
        code: The node's Python code.
        node_dir: Folder to write and run the code in.
        timeout: Maximum run time, in seconds.

    Returns:
        The last `_MAX_OUTPUT` characters of stdout and stderr, the exit code (None if
        it timed out) and whether it timed out.
    """
    (node_dir / "runfile.py").write_text(code)
    try:
        result = subprocess.run(
            [sys.executable, "runfile.py"],
            cwd=node_dir,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as e:
        # On timeout the partial output is always bytes, and either part may be None
        output = "".join(s.decode(errors="replace") for s in (e.stdout, e.stderr) if s)
        return output[-_MAX_OUTPUT:], None, True
    return (result.stdout + result.stderr)[-_MAX_OUTPUT:], result.returncode, False


def _read_metric(node_dir: Path, name: str) -> float | None:
    """
    Read a node's metric from its `metrics.json`.

    Args:
        node_dir: The node's folder.
        name: The idea's metric name, a key in `metrics.json`.

    Returns:
        The metric, or None if the file or value is missing or not a finite number.
    """
    try:
        value = json.loads((node_dir / "metrics.json").read_text())[name]
    except (OSError, ValueError, KeyError, TypeError):
        return None
    is_number = isinstance(value, int | float) and not isinstance(value, bool)
    return float(value) if is_number and math.isfinite(value) else None


def _review_output(idea: dict, node: Node, model: str) -> dict:
    """
    Ask the model whether a node's run had a bug, and to summarise it.

    Args:
        idea: The research idea, from `finalize_idea`.
        node: The node, after its code has run.
        model: Model name as configured in the LiteLLM gateway.

    Returns:
        {"is_bug": bool, "summary": str}.
    """
    prompt = prompts.REVIEW_OUTPUT.format(
        idea=json.dumps(idea, indent=2),
        code=node.code,
        output=node.output,
        metric=idea["Metric"]["name"],
        value=node.metric,
    )
    return call_tool(model, [{"role": "user", "content": prompt}], tools.SUBMIT_REVIEW)


def _review_plots(idea: dict, node_dir: Path, model: str) -> str | None:
    """
    Ask the model for feedback on the plots a node's code saved.

    Args:
        idea: The research idea, from `finalize_idea`.
        node_dir: The node's folder, containing its PNG plots.
        model: Model name as configured in the LiteLLM gateway.

    Returns:
        The feedback, or None if the node saved no plots.
    """
    plots = sorted(node_dir.glob("*.png"))[:_MAX_PLOTS]
    if not plots:
        return None
    text = prompts.REVIEW_PLOTS.format(idea=json.dumps(idea, indent=2))
    content = [{"type": "text", "text": text}]
    content += [image_contents(str(plot)) for plot in plots]
    review = call_tool(
        model, [{"role": "user", "content": content}], tools.ANALYZE_PLOTS
    )
    return review["feedback"]


def evaluate(
    idea: dict, node: Node, node_dir: Path, metric: str, timeout: int, model: str
) -> Node:
    """
    Run a node's code and review it; return the node with its results filled in.

    Args:
        idea: The research idea, from `finalize_idea`.
        node: The node to evaluate, with its code.
        node_dir: Folder to run the node in; created if missing.
        metric: The idea's metric name, a key in `metrics.json`.
        timeout: Maximum run time, in seconds.
        model: Model name as configured in the LiteLLM gateway.

    Returns:
        The same node, with output, exit code, metric, review and plot feedback.
    """
    node_dir.mkdir(parents=True, exist_ok=True)
    node.output, node.exit_code, node.timed_out = _run_script(
        node.code, node_dir, timeout
    )
    node.metric = _read_metric(node_dir, metric)
    review = _review_output(idea, node, model)
    node.summary = review["summary"]
    node.plot_feedback = _review_plots(idea, node_dir, model)
    node.is_bug = (
        review["is_bug"] or node.exit_code != 0 or node.timed_out or node.metric is None
    )
    return node
