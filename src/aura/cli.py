"""Command-line entry point for AuRA."""

import argparse

from aura.constants import TIERS
from aura.run import HARNESSES, run


def main() -> None:
    parser = argparse.ArgumentParser(prog="aura")
    subparsers = parser.add_subparsers(dest="command", required=True)
    run_parser = subparsers.add_parser("run", help="Run a task in the agent sandbox.")
    run_parser.add_argument("task", help="Name of a folder in tasks/.")
    run_parser.add_argument("--harness", choices=HARNESSES, default="claude-code")
    run_parser.add_argument(
        "--model", choices=["claude-haiku-4-5"], default="claude-haiku-4-5"
    )
    run_parser.add_argument(
        "--task-tier",
        type=int,
        choices=range(1, len(TIERS) + 1),
        default=1,
        help=f"Number of task sections to include, in order: {', '.join(TIERS)}.",
    )
    args = parser.parse_args()
    run(args.task, args.harness, args.model, args.task_tier)
