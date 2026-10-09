import pytest

from aura import task


@pytest.fixture
def tasks_dir(tmp_path, monkeypatch):
    (tmp_path / "instructions.md").write_text("Base\n\n{task}")
    task_dir = tmp_path / "task"
    task_dir.mkdir()
    for name in task.TIERS:
        (task_dir / f"{name}.md").write_text(f"{name} text\n")
    monkeypatch.setattr(task, "TASKS_DIR", tmp_path)
    return tmp_path


def test_tiers_stack(tasks_dir):
    prompt = task.build_prompt("task", 2)
    assert prompt == (
        "Base\n\n<requirement>\nrequirement text\n</requirement>\n\n"
        "<research_questions>\nresearch_questions text\n</research_questions>"
    )


def test_task_instructions_override(tasks_dir):
    (tasks_dir / "task" / "instructions.md").write_text("Own: {task}")
    assert (
        task.build_prompt("task", 1)
        == "Own: <requirement>\nrequirement text\n</requirement>"
    )
