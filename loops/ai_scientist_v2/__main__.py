"""Main entry point for the AI scientist v2 harness."""

import argparse
from pathlib import Path

from ai_scientist_v2.nodes import save_bests
from ai_scientist_v2.search import run_stages

_TEST_IDEA = {
    "Title": "Does k-means++ initialisation beat random initialisation?",
    "Short Hypothesis": "k-means++ initialisation reaches lower inertia than random "
    "initialisation on well-separated clusters.",
    "Abstract": "We compare k-means initialisation methods on synthetic blobs.",
    "Experiments": "Generate blobs with scikit-learn's make_blobs: run k-means with "
    "each initialisation over several seeds; report the mean inertia.",
    "Metric": {"name": "inertia", "higher_is_better": False},
}


def main(args: argparse.Namespace) -> None:
    """Run the AI scientist v2 harness with the given arguments."""
    config = {
        "model": args.model,
        "timeout": 600,
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
    _, bests = run_stages(_TEST_IDEA, config, workdir)
    save_bests(bests, workdir / "results" / "best_nodes.json")


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
