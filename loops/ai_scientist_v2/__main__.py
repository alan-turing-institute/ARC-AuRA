"""Main entry point for the AI scientist v2 harness."""

import argparse
import json
from pathlib import Path

from ai_scientist_v2.idea import generate_idea
from ai_scientist_v2.nodes import save_bests
from ai_scientist_v2.search import run_stages


def main(args: argparse.Namespace) -> None:
    """Run the AI scientist v2 harness with the given arguments."""
    config = {
        "model": args.model,
        "timeout": 600,
        "num_reflections": 5,
        "num_drafts": 3,
        "debug_prob": 0.5,
        "max_debug_depth": 3,
        "stage_iters": {
            "initial_implementation": 6,
            "baseline_tuning": 3,
            "creative_research": 3,
            "ablation_studies": 4,
        },
    }
    workdir = Path("/workspace")
    results = workdir / "results"
    results.mkdir(parents=True, exist_ok=True)
    idea = generate_idea(args.prompt, config)
    (results / "idea.json").write_text(json.dumps(idea, indent=2))
    _, bests = run_stages(idea, config, workdir)
    save_bests(bests, results / "best_nodes.json")


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
        help="Names from STAGES to produce outputs for.",
    )
    args = parser.parse_args()

    main(args)
