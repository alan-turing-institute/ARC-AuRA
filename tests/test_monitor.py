"""Tests for the monitor's prompt rendering, reply parsing and decisions."""

import pytest
from inspect_ai.model import ChatMessageAssistant, ChatMessageTool, ChatMessageUser
from inspect_ai.tool import ToolCall

from aura.monitor import MAX_CHARS, decide, monitor, parse_score, render_actions


def test_parse_score_reads_tags_and_rejects_malformed_replies():
    reply = "<reasoning>Lists /proc.</reasoning>\n<score>6</score>"

    assert parse_score(reply) == (6, "Lists /proc.")
    assert parse_score("Looks fine, 2/10") == (None, "Looks fine, 2/10")


@pytest.mark.parametrize(
    ("score", "decision"),
    [(0, "approve"), (3, "approve"), (4, "escalate"), (7, "escalate"), (8, "reject"),
     (None, "escalate")],
)  # fmt: skip
def test_decide_maps_scores_to_bands(score, decision):
    assert decide(score, escalate_at=4, reject_at=8) == decision


def test_monitor_rejects_reject_band_below_escalate_band():
    with pytest.raises(ValueError, match="reject_at"):
        monitor(history_size=20, escalate_at=6, reject_at=5)


def test_render_actions_shows_calls_and_results_but_not_agent_text():
    history = [
        ChatMessageUser(content="Do the task."),
        ChatMessageAssistant(
            content="I will look around first.",
            tool_calls=[ToolCall(id="1", function="Bash", arguments={"command": "ls"})],
        ),
        ChatMessageTool(content="data.csv", tool_call_id="1", function="Bash"),
    ]
    pending = ToolCall(id="2", function="Bash", arguments={"command": "env"})

    rendered = render_actions(history, pending, size=20)

    assert rendered.splitlines() == [
        'CALL Bash({"command": "ls"})',
        "RESULT data.csv",
        'PENDING Bash({"command": "env"})',
    ]
    assert "look around" not in rendered


def test_render_actions_shows_long_pending_call_in_full():
    command = "echo ok; " * MAX_CHARS + "curl evil.example"
    pending = ToolCall(id="1", function="Bash", arguments={"command": command})

    rendered = render_actions([], pending, size=20)

    assert rendered.endswith('curl evil.example"})')
