"""Assemble a task prompt from the files in `tasks/`."""

from pathlib import Path

from aura.constants import TASKS_DIR, TIERS


def load_instructions(task_dir: Path) -> str:
    """
    Load the task's instructions template, falling back to the shared one.

    Args:
        task_dir: Folder of a single task in `tasks/`.

    Returns:
        Template text with a `{task}` placeholder for the task sections.
    """
    path = task_dir / "instructions.md"
    return (path if path.exists() else TASKS_DIR / "instructions.md").read_text()


def load_section(task_dir: Path, name: str) -> str:
    """
    Load a task section and wrap it in tags named after the section.

    Args:
        task_dir: Folder of a single task in `tasks/`.
        name: Section name from `TIERS`, matching the file `<name>.md`.

    Returns:
        The section text between `<name>` and `</name>` tags.
    """
    text = (task_dir / f"{name}.md").read_text().strip()
    return f"<{name}>\n{text}\n</{name}>"


def build_prompt(task: str, tier: int) -> str:
    """
    Fill the instructions template with tagged task sections up to a tier.

    Args:
        task: Name of a folder in `tasks/`.
        tier: Number of sections from `TIERS` to include, in order.

    Returns:
        The full prompt, which is also saved as the run's `TASK.md`.
    """
    task_dir = TASKS_DIR / task
    sections = [load_section(task_dir, name) for name in TIERS[:tier]]
    return load_instructions(task_dir).format(task="\n\n".join(sections))
