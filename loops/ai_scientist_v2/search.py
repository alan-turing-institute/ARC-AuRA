"""
The four-stage tree search over nodes.

Adapted from AI Scientist-v2's `ai_scientist/treesearch/agent_manager.py` (stages and
their completion) and `parallel_agent.py` (`_select_parallel_nodes`); see LICENSE.

`cfg` keys used here: "model", "timeout", "num_drafts", "debug_prob",
"max_debug_depth" and "stage_iters" (iteration cap per stage name).
"""

from pathlib import Path
from random import Random

# import ai_scientist_v2.operators as ops
from ai_scientist_v2.nodes import Node


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
        stage: Key of `ops.STAGE_GOALS`.
        nodes: This stage's nodes.
        start: Previous stage's best node, which this stage builds on; None in stage 1.
        best: From `best_node`; None if no node works yet.
        cfg: Uses "num_drafts", "debug_prob" and "max_debug_depth".
        rng: For the debug draw and the choice of buggy leaf; seed it in tests.

    Returns:
        The operator name and the node to apply it to (None for a draft).
    """
    # 1. Stage 1 ("initial_implementation", not "1") with fewer than
    #    cfg["num_drafts"] drafts (op == "draft") -> ("draft", None).
    # 2. With probability cfg["debug_prob"] (rng.random() < ...), debug a buggy leaf:
    #    is_bug, no child in `nodes` (no n.parent_id == its id), and
    #    debug_depth < cfg["max_debug_depth"]. Pick one with rng.choice ->
    #    ("debug", leaf). If there are none, fall through.
    # 3. Otherwise by stage:
    #    - baseline_tuning -> ("tune", start); ablation_studies -> ("ablate", start)
    #    - initial_implementation, creative_research -> ("improve", best), or
    #      ("draft", None) if best is None (only possible in stage 1)
    pass


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
    # - Keep only working nodes (not is_bug). None -> return None; one -> return it.
    # - Otherwise call_tool (from ai_scientist_v2.llm) with a forced tool, e.g.
    #   `_SELECT_TOOL` "select_best_node" with {"id", "reason"}. The prompt lists
    #   each node's id, metric, summary and plot_feedback (upstream: `_select_best`
    #   in parallel_agent.py).
    # - If the returned id isn't a candidate, fall back to max/min by metric,
    #   using idea["Metric"]["higher_is_better"].
    pass


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
        stage: Key of `ops.STAGE_GOALS`.
        nodes: This stage's nodes.
        start: Previous stage's best node; None in stage 1.
        cfg: Uses "stage_iters".
        higher_is_better: Direction of the idea's metric.
        judged_done: From `_tuning_done`; only used in baseline_tuning.

    Returns:
        Whether the stage has finished.
    """
    # - Always done at the cap: len(nodes) >= cfg["stage_iters"][stage].
    # - initial_implementation: done at the first working node.
    # - baseline_tuning: done if a working node beats start.metric (in the
    #   direction of higher_is_better) and judged_done.
    # - creative_research, ablation_studies: only the cap.
    pass


def run_stages(
    idea: dict, cfg: dict, workdir: Path
) -> tuple[list[Node], dict[str, Node]]:
    """
    Run the four stages, each building on the previous stage's best node.

    Args:
        idea: The research idea, from `finalize_idea`, including its "Metric".
        cfg: All keys listed in the module docstring.
        workdir: Run folder; nodes go in `tree/<id>/`, the journal in
            `tree/journal.json`.

    Returns:
        All nodes, and each finished stage's best node by stage name.
    """
    # rng = Random(); all_nodes = []; bests = {}; start = None
    # For each stage in ops.STAGE_GOALS (in order):
    #   brief = ops.stage_brief(idea, stage, cfg["timeout"]); nodes = []
    #   Loop:
    #     best = best_node(model, idea, nodes + [start] if start else nodes)
    #     op, parent = select_node(stage, nodes, start, best, cfg, rng)
    #     plan, code = _propose(op, cfg["model"], brief, summarise_journal(...),
    #                           parent, _tried(nodes))
    #     node = _make_node(str(len(all_nodes)), stage, op, parent, plan, code)
    #     evaluate(idea, node, workdir / "tree" / node.id, idea["Metric"]["name"],
    #              cfg["timeout"], cfg["model"])
    #     Append to nodes and all_nodes; save_journal(all_nodes, .../journal.json);
    #     print one JSON "node" event line (see the plan's Outputs).
    #     judged = stage == "baseline_tuning" and not node.is_bug and
    #              _tuning_done(model, idea, nodes)   # skip the call otherwise
    #     Break if stage_done(...).
    #   bests[stage] = best_node(...) over nodes + start; print a "stage_end" event;
    #   start = bests[stage]. If start is None (stage 1 found nothing), stop.
    # Catch BudgetExceeded around the loop: stop and return what there is; the
    # journal is already saved.
    pass


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
    # A match on op, e.g. case "tune": return ops.tune(model, brief, parent, tried)
    pass


def _make_node(
    node_id: str, stage: str, op: str, parent: Node | None, plan: str, code: str
) -> Node:
    """
    Create an unevaluated node.

    Args:
        node_id: Unique ID, e.g. the count of nodes so far.
        stage: Key of `ops.STAGE_GOALS`.
        op: The operator that made it.
        parent: The node it was made from; None for a draft.
        plan: The model's plan.
        code: The script.

    Returns:
        The node, with parent_id and debug_depth set.
    """
    # debug_depth: parent.debug_depth + 1 if op == "debug", else 0.
    pass


def _tried(nodes: list[Node]) -> list[str]:
    """Names of the settings or ablations tried: first lines of their plans."""
    # [n.plan.split("\n")[0] for n in nodes if n.op in ("tune", "ablate")]
    pass


def _tuning_done(model: str, idea: dict, nodes: list[Node]) -> bool:
    """
    Ask the model whether baseline tuning has gone far enough.

    Args:
        model: Model name as configured in the LiteLLM gateway.
        idea: The research idea, from `finalize_idea`.
        nodes: This stage's nodes.

    Returns:
        The model's verdict.
    """
    # call_tool with a forced tool, e.g. "evaluate_stage" with {"is_complete",
    # "reason"}; the prompt gives the stage goals (ops.STAGE_GOALS) and
    # summarise_journal(nodes). Upstream: `_check_substage_completion`.
    pass
