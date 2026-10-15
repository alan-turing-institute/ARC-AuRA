"""Tests for the per-run gateway key lifecycle in src/aura/run.py."""

import json
import subprocess

import pytest

from aura import run

RUN_KEY = "sk-run-secret"


@pytest.fixture
def fake_run(tmp_path, monkeypatch):
    """Replace the gateway, Docker and task prompt with fakes; return what they saw."""
    seen = {"blocked": []}

    def fake_create_run_key(run_id, model, max_budget, max_duration, metadata):
        seen["limits"] = (max_budget, max_duration)
        return RUN_KEY

    def fake_compose_run(command, run_dir, run_key):
        seen["run_key"] = run_key

    monkeypatch.setenv("LITELLM_MASTER_KEY", "sk-master-secret")
    monkeypatch.setattr(run, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(run, "SPEND_WAIT", 0)
    monkeypatch.setattr(run, "build_prompt", lambda task, tier: "Do the task.")
    monkeypatch.setattr(run, "create_run_key", fake_create_run_key)
    monkeypatch.setattr(run, "block_key", seen["blocked"].append)
    monkeypatch.setattr(run, "get_spend", lambda key: 0.25)
    monkeypatch.setattr(run, "compose_run", fake_compose_run)
    return seen


def cost_json(tmp_path) -> str:
    (run_dir,) = (tmp_path / "runs").iterdir()
    return (run_dir / "cost.json").read_text()


def test_run_uses_its_own_key_and_records_cost(fake_run, tmp_path):
    run.run(
        "task", "claude-code", "claude-haiku-4-5", 1, budget=0.5, max_duration="10m"
    )

    assert fake_run["run_key"] == RUN_KEY  # never the master key
    assert fake_run["limits"] == (0.5, "10m")
    assert fake_run["blocked"] == [RUN_KEY]
    cost = cost_json(tmp_path)
    assert json.loads(cost)["spend_usd"] == 0.25
    assert RUN_KEY not in cost


def test_key_is_blocked_and_cost_recorded_when_run_fails(
    fake_run, tmp_path, monkeypatch
):
    def failing_compose_run(command, run_dir, run_key):
        raise subprocess.CalledProcessError(1, "docker")

    monkeypatch.setattr(run, "compose_run", failing_compose_run)

    with pytest.raises(subprocess.CalledProcessError):
        run.run("task", "claude-code", "claude-haiku-4-5", 1, 2.0, "1h")

    assert fake_run["blocked"] == [RUN_KEY]
    assert json.loads(cost_json(tmp_path))["spend_usd"] == 0.25
