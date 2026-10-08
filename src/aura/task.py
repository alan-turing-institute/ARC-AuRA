"""Assemble a task prompt from the files in `tasks/`."""

from pathlib import Path

from aura.constants import TASKS_DIR, TIERS


def load_instructions(task_dir: Path) -> str:
    """Load the task's instructions template, falling back to the shared one."""
    path = task_dir / "instructions.md"
    return (path if path.exists() else TASKS_DIR / "instructions.md").read_text()


def build_prompt(task: str, tier: str) -> str:
    """Fill the instructions template with task sections up to a tier.

    Args:
        task: Name of a folder in `tasks/`.
        tier: Last entry of `TIERS` to include.

    Returns:
        The full prompt.
    """
    task_dir = TASKS_DIR / task
    sections = [
        (task_dir / f"{name}.md").read_text().strip()
        for name in TIERS[: TIERS.index(tier) + 1]
    ]
    return load_instructions(task_dir).format(task="\n\n".join(sections))
