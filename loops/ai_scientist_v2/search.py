"""
The four-phase tree search over nodes.

Adapted from AI Scientist-v2's `ai_scientist/treesearch/agent_manager.py` (its
stages, here phases, and their completion), `parallel_agent.py` (`_select_parallel_nodes`) and `journal.py`
(`get_best_node`); see LICENSE.

`cfg` keys used here: "model", "timeout", "num_drafts", "debug_prob",
"max_debug_depth" and "phase_iters" (iteration cap per phase name).
"""

from pathlib import Path
from random import Random

import ai_scientist_v2.operators as ops
from ai_scientist_v2 import prompts, tools
from ai_scientist_v2.execute import evaluate
from ai_scientist_v2.llm import BudgetExceeded, ModelReplyError, call_tool
from ai_scientist_v2.nodes import (
    Node,
    emit,
    save_bests,
    save_journal,
    summarise_journal,
)


def select_node(
    phase: str,
    nodes: list[Node],
    start: Node | None,
    best: Node | None,
    cfg: dict,
    rng: Random,
) -> tuple[str, Node | None]:
    """
    Choose the next operator and the node to apply it to.

    Args:
        phase: Key of `prompts.PHASE_GOALS`.
        nodes: This phase's nodes.
        start: Previous phase's best node, which this phase builds on; None in phase 1.
        best: From `best_node`; None if no node works yet.
        cfg: Uses "num_drafts", "debug_prob" and "max_debug_depth".
        rng: For the debug draw and the choice of buggy leaf; seed it in tests.

    Returns:
        The operator name and the node to apply it to (None for a draft).
    """
    drafts = sum(n.op == "draft" for n in nodes)
    if phase == "initial_implementation" and drafts < cfg["num_drafts"]:
        return "draft", None
    leaves = _buggy_leaves(nodes, cfg["max_debug_depth"])
    if rng.random() < cfg["debug_prob"] and leaves:
        return "debug", rng.choice(leaves)
    if phase == "baseline_tuning":
        return "tune", start
    if phase == "ablation_studies":
        return "ablate", start
    return ("improve", best) if best else ("draft", None)


def best_node(model: str, idea: dict, nodes: list[Node]) -> Node | None:
    """
    Ask the model which working node is best, falling back to the best metric if
    its reply is unusable or names no working node.

    Args:
        model: Model name as configured in the LiteLLM gateway.
        idea: The research idea, from `finalize_idea`, including its "Metric".
        nodes: Candidates: this phase's nodes and its start node.

    Returns:
        The best working node, or None if none works.
    """
    working = [n for n in nodes if n.is_bug is False]
    if len(working) <= 1:
        return working[0] if working else None
    metric = idea["Metric"]
    direction = "higher" if metric["higher_is_better"] else "lower"
    candidates = "\n\n".join(
        f"ID: {n.id}\nMetric: {n.metric}\nReview: {n.summary}\n"
        f"Plot feedback: {n.plot_feedback or 'none'}"
        for n in working
    )
    prompt = prompts.SELECT_BEST.format(
        metric=metric["name"], direction=direction, candidates=candidates
    )
    messages = [{"role": "user", "content": prompt}]
    try:
        reply = call_tool(model, messages, tools.SELECT_BEST)
    except ModelReplyError as e:
        emit("model_error", step="select_best", error=str(e))
        return _best_metric(working, metric["higher_is_better"])
    chosen = [n for n in working if n.id == reply["selected_id"]]
    return chosen[0] if chosen else _best_metric(working, metric["higher_is_better"])


def phase_done(phase: str, nodes: list[Node], judged_done: bool) -> bool:
    """
    Decide whether a phase has met its goal; `_run_phase` enforces the iteration cap.

    Args:
        phase: Key of `prompts.PHASE_GOALS`.
        nodes: This phase's nodes.
        judged_done: Whether the best node beats the phase's start node and the
            model judges tuning done; only used in baseline_tuning.

    Returns:
        Whether the phase has met its goal.
    """
    if phase == "initial_implementation":
        return any(n.is_bug is False for n in nodes)
    if phase == "baseline_tuning":
        return judged_done
    return False


def run_phases(
    idea: dict, cfg: dict, workdir: Path
) -> tuple[list[Node], dict[str, Node], list[str]]:
    """
    Run the four phases, each building on the previous phase's best node.

    Stops early if phase 1 finds no working node, or if the run's budget is spent.
    Saves the best nodes however it ends, even on an unexpected error.

    NB: bests is modified in place by _run_phase, so it survives a BudgetExceeded
        raised mid-phase.

    Args:
        idea: The research idea, from `finalize_idea`, including its "Metric".
        cfg: All keys listed in the module docstring.
        workdir: Run folder; nodes go in `tree/<id>/`, the journal in
            `tree/journal.json` and the best nodes in `tree/best_nodes.json`.

    Returns:
        All nodes; each phase's best node by phase name, including the judge's
        latest pick in a phase the budget cut short; and the phases that finished.
    """
    rng = Random()
    tree = workdir / "tree"
    tree.mkdir(parents=True, exist_ok=True)
    all_nodes, bests, finished, start = [], {}, [], None
    try:
        for phase in prompts.PHASE_GOALS:
            start = _run_phase(phase, start, idea, cfg, rng, all_nodes, bests, tree)
            if start is None:
                break
            finished.append(phase)
    except BudgetExceeded:
        emit("budget_exceeded", nodes=len(all_nodes))
    finally:
        save_bests(bests, finished, tree / "best_nodes.json")
    return all_nodes, bests, finished


def _run_phase(
    phase: str,
    start: Node | None,
    idea: dict,
    cfg: dict,
    rng: Random,
    all_nodes: list[Node],
    bests: dict[str, Node],
    tree: Path,
) -> Node | None:
    """
    Grow the tree for one phase until `phase_done` or the phase's iteration cap.

    An unusable model reply costs one iteration: a failed proposal makes no node,
    and a failed review marks the node buggy.

    Args:
        phase: Key of `prompts.PHASE_GOALS`.
        start: Previous phase's best node; None in phase 1.
        idea: The research idea, from `finalize_idea`, including its "Metric".
        cfg: All keys listed in the module docstring.
        rng: For `select_node`.
        all_nodes: Every node so far; new nodes are appended, so they survive a
            `BudgetExceeded` raised mid-phase.
        bests: Each phase's best node; this phase's is updated after every
            judgement, so it survives a `BudgetExceeded` too.
        tree: Folder for the nodes' folders and `journal.json`.

    Returns:
        The phase's best node, or None if none works.
    """
    model, timeout = cfg["model"], cfg["timeout"]
    brief = ops.phase_brief(idea, phase, timeout)
    nodes, best = [], start
    for _ in range(cfg["phase_iters"][phase]):
        op, parent = select_node(phase, nodes, start, best, cfg, rng)
        memory = summarise_journal(all_nodes)
        try:
            plan, code = _propose(op, model, brief, memory, parent, _tried(nodes))
        except ModelReplyError as e:
            emit("model_error", phase=phase, step=op, error=str(e))
            continue
        node = _make_node(f"{len(all_nodes):03d}", phase, op, parent, plan, code)
        nodes.append(node)
        all_nodes.append(node)
        # Record the attempt even if its review is cut short, e.g. by the budget
        try:
            metric = idea["Metric"]["name"]
            evaluate(idea, node, tree / node.id, metric, timeout, model)
        except ModelReplyError as e:
            node.is_bug, node.summary = True, f"Review failed: {e}"
        finally:
            save_journal(all_nodes, tree / "journal.json")
            emit(
                "node",
                phase=phase,
                id=node.id,
                parent_id=node.parent_id,
                op=op,
                is_bug=node.is_bug,
                metric=node.metric,
                summary=node.summary,
            )
        best = best_node(model, idea, nodes + ([start] if start else []))
        if best:
            bests[phase] = best
        # Only ask the model once the best node beats the phase's start node, so
        # tuning can't end on a pick that is worse than the baseline
        judged = (
            phase == "baseline_tuning"
            and _beats(best, start, idea["Metric"]["higher_is_better"])
            and _tuning_done(model, best)
        )
        if phase_done(phase, nodes, judged):
            break
    emit("phase_end", phase=phase, best=best.id if best else None)
    return best


def _buggy_leaves(nodes: list[Node], max_debug_depth: int) -> list[Node]:
    """Buggy nodes with no children yet, and debug depth within the limit."""
    parents = {n.parent_id for n in nodes}
    return [
        n
        for n in nodes
        if n.is_bug and n.id not in parents and n.debug_depth < max_debug_depth
    ]


def _beats(node: Node, other: Node, higher_is_better: bool) -> bool:
    """Whether a node's metric is strictly better than another's."""
    return (
        node.metric > other.metric if higher_is_better else node.metric < other.metric
    )


def _best_metric(nodes: list[Node], higher_is_better: bool) -> Node:
    """The node with the best metric, in the metric's direction."""
    pick = max if higher_is_better else min
    return pick(nodes, key=lambda n: n.metric)


def _propose(
    op: str,
    model: str,
    brief: str,
    memory: str,
    parent: Node | None,
    tried: list[str],
) -> tuple[str, str]:
    """
    Call the operator named `op` with the arguments it takes.

    Args:
        op: draft, debug, improve, tune or ablate.
        model: Model name as configured in the LiteLLM gateway.
        brief: From `ops.phase_brief`.
        memory: From `summarise_journal`.
        parent: The node to change; None for a draft.
        tried: From `_tried`; used by tune and ablate.

    Returns:
        The plan and the script.
    """
    match op:
        case "draft":
            return ops.draft(model, brief, memory)
        case "debug":
            return ops.debug(model, brief, parent)
        case "improve":
            return ops.improve(model, brief, memory, parent)
        case "tune":
            return ops.tune(model, brief, parent, tried)
        case "ablate":
            return ops.ablate(model, brief, parent, tried)


def _make_node(
    node_id: str, phase: str, op: str, parent: Node | None, plan: str, code: str
) -> Node:
    """
    Create an unevaluated node.

    Args:
        node_id: Unique ID, e.g. the count of nodes so far.
        phase: Key of `prompts.PHASE_GOALS`.
        op: The operator that made it.
        parent: The node it was made from; None for a draft.
        plan: The model's plan.
        code: The script.

    Returns:
        The node, with parent_id and debug_depth set.
    """
    return Node(
        id=node_id,
        phase=phase,
        op=op,
        parent_id=parent.id if parent else None,
        plan=plan,
        code=code,
        debug_depth=parent.debug_depth + 1 if op == "debug" else 0,
    )


def _tried(nodes: list[Node]) -> list[str]:
    """Names of the settings or ablations tried: first lines of their plans."""
    return [n.plan.split("\n")[0] for n in nodes if n.op in ("tune", "ablate")]


def _tuning_done(model: str, best: Node) -> bool:
    """
    Ask the model whether baseline tuning has gone far enough, from its best node.

    Args:
        model: Model name as configured in the LiteLLM gateway.
        best: The phase's best node, which beats the phase's start node.

    Returns:
        The model's verdict; False if its reply is unusable.
    """
    prompt = prompts.TUNING_DONE.format(
        plan=best.plan,
        metric=best.metric,
        summary=best.summary,
        plot_feedback=best.plot_feedback or "none",
        goals=prompts.PHASE_GOALS["baseline_tuning"],
    )
    messages = [{"role": "user", "content": prompt}]
    try:
        reply = call_tool(model, messages, tools.PHASE_DONE)
    except ModelReplyError as e:
        emit("model_error", step="tuning_done", error=str(e))
        return False
    return reply["is_complete"]
