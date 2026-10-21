"""
The four-stage tree search over nodes.

Adapted from AI Scientist-v2's `ai_scientist/treesearch/agent_manager.py` (stages and
their completion), `parallel_agent.py` (`_select_parallel_nodes`) and `journal.py`
(`get_best_node`); see LICENSE.

`cfg` keys used here: "model", "timeout", "num_drafts", "debug_prob",
"max_debug_depth" and "stage_iters" (iteration cap per stage name).
"""

from pathlib import Path
from random import Random

import ai_scientist_v2.operators as ops
from ai_scientist_v2 import prompts, tools
from ai_scientist_v2.execute import evaluate
from ai_scientist_v2.llm import BudgetExceeded, call_tool
from ai_scientist_v2.nodes import Node, emit, save_journal, summarise_journal


def select_node(
    stage: str,
    nodes: list[Node],
    start: Node | None,
    best: Node | None,
    cfg: dict,
    rng: Random,
) -> tuple[str, Node | None]:
    """
    Choose the next operator and the node to apply it to.

    Args:
        stage: Key of `prompts.STAGE_GOALS`.
        nodes: This stage's nodes.
        start: Previous stage's best node, which this stage builds on; None in stage 1.
        best: From `best_node`; None if no node works yet.
        cfg: Uses "num_drafts", "debug_prob" and "max_debug_depth".
        rng: For the debug draw and the choice of buggy leaf; seed it in tests.

    Returns:
        The operator name and the node to apply it to (None for a draft).
    """
    drafts = sum(n.op == "draft" for n in nodes)
    if stage == "initial_implementation" and drafts < cfg["num_drafts"]:
        return "draft", None
    leaves = _buggy_leaves(nodes, cfg["max_debug_depth"])
    if rng.random() < cfg["debug_prob"] and leaves:
        return "debug", rng.choice(leaves)
    if stage == "baseline_tuning":
        return "tune", start
    if stage == "ablation_studies":
        return "ablate", start
    return ("improve", best) if best else ("draft", None)


def best_node(model: str, idea: dict, nodes: list[Node]) -> Node | None:
    """
    Ask the model which working node is best, falling back to the best metric.

    Args:
        model: Model name as configured in the LiteLLM gateway.
        idea: The research idea, from `finalize_idea`, including its "Metric".
        nodes: Candidates: this stage's nodes and its start node.

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
    reply = call_tool(model, [{"role": "user", "content": prompt}], tools.SELECT_BEST)
    chosen = [n for n in working if n.id == reply["selected_id"]]
    return chosen[0] if chosen else _best_metric(working, metric["higher_is_better"])


def stage_done(
    stage: str,
    nodes: list[Node],
    start: Node | None,
    cfg: dict,
    higher_is_better: bool,
    judged_done: bool,
) -> bool:
    """
    Decide whether a stage has finished.

    Args:
        stage: Key of `prompts.STAGE_GOALS`.
        nodes: This stage's nodes.
        start: Previous stage's best node; None in stage 1.
        cfg: Uses "stage_iters".
        higher_is_better: Direction of the idea's metric.
        judged_done: From `_tuning_done`; only used in baseline_tuning.

    Returns:
        Whether the stage has finished.
    """
    working = [n for n in nodes if n.is_bug is False]
    if len(nodes) >= cfg["stage_iters"][stage]:
        return True
    if stage == "initial_implementation":
        return bool(working)
    if stage == "baseline_tuning":
        beats = [n for n in working if _beats(n, start, higher_is_better)]
        return judged_done and bool(beats)
    return False


def run_stages(
    idea: dict, cfg: dict, workdir: Path
) -> tuple[list[Node], dict[str, Node], list[str]]:
    """
    Run the four stages, each building on the previous stage's best node.

    Stops early if stage 1 finds no working node, or if the run's budget is spent.

    Args:
        idea: The research idea, from `finalize_idea`, including its "Metric".
        cfg: All keys listed in the module docstring.
        workdir: Run folder; nodes go in `tree/<id>/`, the journal in
            `tree/journal.json`.

    Returns:
        All nodes; each stage's best node by stage name, including the judge's
        latest pick in a stage the budget cut short; and the stages that finished.
    """
    rng = Random()
    tree = workdir / "tree"
    tree.mkdir(parents=True, exist_ok=True)
    all_nodes, bests, finished, start = [], {}, [], None
    try:
        for stage in prompts.STAGE_GOALS:
            start = _run_stage(stage, start, idea, cfg, rng, all_nodes, bests, tree)
            if start is None:
                break
            finished.append(stage)
    except BudgetExceeded:
        emit("budget_exceeded", nodes=len(all_nodes))
    return all_nodes, bests, finished


def _run_stage(
    stage: str,
    start: Node | None,
    idea: dict,
    cfg: dict,
    rng: Random,
    all_nodes: list[Node],
    bests: dict[str, Node],
    tree: Path,
) -> Node | None:
    """
    Grow the tree for one stage until `stage_done`.

    Args:
        stage: Key of `prompts.STAGE_GOALS`.
        start: Previous stage's best node; None in stage 1.
        idea: The research idea, from `finalize_idea`, including its "Metric".
        cfg: All keys listed in the module docstring.
        rng: For `select_node`.
        all_nodes: Every node so far; new nodes are appended, so they survive a
            `BudgetExceeded` raised mid-stage.
        bests: Each stage's best node; this stage's is updated after every
            judgement, so it survives a `BudgetExceeded` too.
        tree: Folder for the nodes' folders and `journal.json`.

    Returns:
        The stage's best node, or None if none works.
    """
    model, timeout = cfg["model"], cfg["timeout"]
    brief = ops.stage_brief(idea, stage, timeout)
    nodes, best, done = [], start, False
    while not done:
        op, parent = select_node(stage, nodes, start, best, cfg, rng)
        memory = summarise_journal(all_nodes)
        plan, code = _propose(op, model, brief, memory, parent, _tried(nodes))
        node = _make_node(f"{len(all_nodes):03d}", stage, op, parent, plan, code)
        nodes.append(node)
        all_nodes.append(node)
        # Record the attempt even if its review is cut short, e.g. by the budget
        try:
            metric = idea["Metric"]["name"]
            evaluate(idea, node, tree / node.id, metric, timeout, model)
        finally:
            save_journal(all_nodes, tree / "journal.json")
            emit(
                "node",
                stage=stage,
                id=node.id,
                parent_id=node.parent_id,
                op=op,
                is_bug=node.is_bug,
                metric=node.metric,
                summary=node.summary,
            )
        best = best_node(model, idea, nodes + ([start] if start else []))
        if best:
            bests[stage] = best
        # Only ask the model once tuning has found a new best, as upstream does
        judged = (
            stage == "baseline_tuning"
            and best is not start
            and _tuning_done(model, best)
        )
        done = stage_done(
            stage, nodes, start, cfg, idea["Metric"]["higher_is_better"], judged
        )
    emit("stage_end", stage=stage, best=best.id if best else None)
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
        brief: From `ops.stage_brief`.
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
    node_id: str, stage: str, op: str, parent: Node | None, plan: str, code: str
) -> Node:
    """
    Create an unevaluated node.

    Args:
        node_id: Unique ID, e.g. the count of nodes so far.
        stage: Key of `prompts.STAGE_GOALS`.
        op: The operator that made it.
        parent: The node it was made from; None for a draft.
        plan: The model's plan.
        code: The script.

    Returns:
        The node, with parent_id and debug_depth set.
    """
    return Node(
        id=node_id,
        stage=stage,
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
        best: The stage's best node, which beats the stage's start node.

    Returns:
        The model's verdict.
    """
    prompt = prompts.TUNING_DONE.format(
        plan=best.plan,
        metric=best.metric,
        summary=best.summary,
        plot_feedback=best.plot_feedback or "none",
        goals=prompts.STAGE_GOALS["baseline_tuning"],
    )
    reply = call_tool(model, [{"role": "user", "content": prompt}], tools.STAGE_DONE)
    return reply["is_complete"]
