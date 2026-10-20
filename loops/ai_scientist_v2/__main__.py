"""Main entry point for the AI scientist v2 harness."""

import argparse
import json
from pathlib import Path

from ai_scientist_v2 import report
from ai_scientist_v2.idea import generate_idea
from ai_scientist_v2.llm import BudgetExceeded
from ai_scientist_v2.nodes import emit, save_bests
from ai_scientist_v2.operators import STAGE_GOALS
from ai_scientist_v2.search import run_stages

# A copy of `aura.constants.STAGES`, which the container can't import
STAGES = (
    "research_questions",
    "lit_review",
    "research_design",
    "experiments",
    "analysis",
    "report",
)

# The stages that need each step; the idea step always runs
_STEP_STAGES = {
    "lit_review": {"lit_review"},
    "search": {"experiments", "analysis", "report"},
    "analysis": {"analysis", "report"},
    "report": {"report"},
}


def steps_needed(stages: list[str]) -> set[str]:
    """
    The steps to run after the idea step, for the requested stages.

    Args:
        stages: Names from `STAGES` to produce outputs for.

    Returns:
        Some of "lit_review", "search", "analysis" and "report".
    """
    return {step for step, needs in _STEP_STAGES.items() if needs & set(stages)}


def main(args: argparse.Namespace) -> None:
    config = {
        "model": args.model,
        "timeout": args.timeout,
        "num_reflections": args.num_reflections,
        "num_drafts": args.num_drafts,
        "debug_prob": args.debug_prob,
        "max_debug_depth": args.max_debug_depth,
        "stage_iters": dict(zip(STAGE_GOALS, args.stage_iters, strict=True)),
    }
    model, stages, steps = args.model, set(args.stages), steps_needed(args.stages)
    workdir = Path("/workspace")
    results = workdir / "results"
    results.mkdir(parents=True, exist_ok=True)
    try:
        idea, papers = generate_idea(args.prompt, config)
        (workdir / "idea.json").write_text(json.dumps(idea, indent=2))
        if "research_questions" in stages:
            text = report.research_questions(idea)
            report.save_output(results, "research_questions", text)
        if "research_design" in stages:
            text = report.research_design(idea)
            report.save_output(results, "research_design", text)
        if "lit_review" in steps:
            text = report.write_lit_review(args.prompt, idea, papers, model)
            report.save_output(results, "lit_review", text)
        if "search" not in steps:
            return
        nodes, bests = run_stages(idea, config, workdir)
        save_bests(bests, workdir / "tree" / "best_nodes.json")
        if "experiments" in stages:
            report.write_experiments(bests, workdir / "tree", results / "experiments")
        if "analysis" not in steps:
            return
        analysis = report.write_analysis(idea, bests, nodes, model)
        if "analysis" in stages:
            report.save_output(results, "analysis", analysis)
        if "report" in steps:
            rounds = args.num_cite_rounds
            cited = report.gather_citations(idea, analysis, papers, rounds, model)
            text = report.write_report(idea, analysis, bests, cited, model)
            report.save_output(results, "report", text)
    except BudgetExceeded:
        emit("budget_exceeded")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run AI Scientist v2 harness.")
    parser.add_argument("prompt", help="Full task prompt.")
    parser.add_argument(
        "--model",
        required=True,
        help="Model name as configured in the LiteLLM gateway.",
    )
    parser.add_argument(
        "--stages",
        nargs="+",
        required=True,
        choices=STAGES,
        help="Stages to produce outputs for.",
    )
    parser.add_argument(
        "--timeout", type=int, default=600, help="Script timeout, in seconds."
    )
    parser.add_argument(
        "--num-reflections",
        type=int,
        default=5,
        help="Most rounds of the idea step before the idea must be finalised.",
    )
    parser.add_argument(
        "--num-drafts", type=int, default=3, help="Drafts to make in search stage 1."
    )
    parser.add_argument(
        "--debug-prob",
        type=float,
        default=0.5,
        help="Chance of debugging a buggy node instead of improving the best one.",
    )
    parser.add_argument(
        "--max-debug-depth",
        type=int,
        default=3,
        help="Most debug steps in a row on one line of nodes.",
    )
    parser.add_argument(
        "--stage-iters",
        type=int,
        nargs=4,
        default=[6, 3, 3, 4],
        help="Most nodes in each of the four search stages, in order.",
    )
    parser.add_argument(
        "--num-cite-rounds",
        type=int,
        default=5,
        help="Most rounds of searching for the report's citations.",
    )
    main(parser.parse_args())
