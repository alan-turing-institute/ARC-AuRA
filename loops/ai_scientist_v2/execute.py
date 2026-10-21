"""
Run a node's code and review its output and plots.

Adapted from AI Scientist-v2's `ai_scientist/treesearch/parallel_agent.py`
(`parse_exec_result`, `_analyze_plots_with_vlm`); see LICENSE.
"""

import contextlib
import json
import math
import os
import resource
import signal
import subprocess
import sys
from pathlib import Path

from ai_scientist_v2 import prompts, tools
from ai_scientist_v2.llm import call_tool, image_contents
from ai_scientist_v2.nodes import Node

_MAX_OUTPUT = 5000  # characters of output kept, from the end, as upstream does
_MAX_PLOTS = 10
# Largest file a script may write, its output included; the run folder is on the host
_MAX_FILE_BYTES = 100 * 1024**2


def _run_script(
    code: str, node_dir: Path, timeout: int
) -> tuple[str, int | None, bool]:
    """
    Write code to `runfile.py` in a node's folder and run it there with a timeout.

    Args:
        code: The node's Python code.
        node_dir: Folder to write and run the code in; its output goes to
            `output.txt` there.
        timeout: Maximum run time, in seconds.

    Returns:
        The last `_MAX_OUTPUT` characters of stdout and stderr, with a line saying why
        the script failed if it did; the exit code (None if it timed out); and whether
        it timed out.
    """
    (node_dir / "runfile.py").write_text(code)
    log = node_dir / "output.txt"
    # Output goes to a file, so a verbose script can't fill the harness's memory
    with log.open("w") as f:
        # Its own process group, so the script's workers can be killed with it
        process = subprocess.Popen(
            [sys.executable, "-u", "runfile.py"],
            cwd=node_dir,
            stdout=f,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            preexec_fn=_limit_file_size,
        )
        try:
            exit_code, timed_out = process.wait(timeout), False
        except subprocess.TimeoutExpired:
            exit_code, timed_out = None, True
        finally:
            _kill_group(process)
    output = log.read_text(errors="replace")[-_MAX_OUTPUT:]
    ending = _ending(exit_code, timeout, log.stat().st_size)
    return output + ending, exit_code, timed_out


def _ending(exit_code: int | None, timeout: int, size: int) -> str:
    """
    A line saying why a script failed, for its review and debugging; added after the
    output is cut to `_MAX_OUTPUT`, so it's always seen.

    Args:
        exit_code: The script's exit code; None if it timed out.
        timeout: The script's timeout, in seconds.
        size: Size of its output file, in bytes.

    Returns:
        The line, or "" if the script succeeded.
    """
    if exit_code is None:
        return f"\n[Stopped: the script hit its {timeout}-second timeout.]"
    if size >= _MAX_FILE_BYTES:
        limit = _MAX_FILE_BYTES // 1024**2
        return f"\n[Stopped: the output reached the {limit} MB file size limit.]"
    if exit_code < 0:
        return f"\n[Stopped: the script was killed by signal {-exit_code}.]"
    if exit_code:
        return f"\n[The script exited with code {exit_code}.]"
    return ""


def _kill_group(process: subprocess.Popen) -> None:
    """Kill a script's process group, including any workers it left, and reap it."""
    with contextlib.suppress(ProcessLookupError):
        os.killpg(process.pid, signal.SIGKILL)
    process.wait()


def _limit_file_size() -> None:
    """Make the script's writes fail once a file reaches `_MAX_FILE_BYTES`."""
    resource.setrlimit(resource.RLIMIT_FSIZE, (_MAX_FILE_BYTES, _MAX_FILE_BYTES))


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
