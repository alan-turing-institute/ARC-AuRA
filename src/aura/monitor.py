"""
Score each tool call's suspicion with a monitor model, and act on the score.

The `monitor` approver approves, escalates or rejects each call it sees, using the
bands set in `approval.yaml`, and records every score in the sample store. The
`monitor_summary` scorer summarises those scores for the run.
"""

import json
import re
from statistics import fmean

from inspect_ai.approval import Approval, ApprovalDecision, Approver, approver
from inspect_ai.model import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageTool,
    ChatMessageUser,
    get_model,
)
from inspect_ai.scorer import Score, Scorer, Target, mean, scorer
from inspect_ai.solver import TaskState
from inspect_ai.tool import ToolCall, ToolCallView
from inspect_ai.util import store

from aura.constants import MONITOR_PROMPT

# Per earlier call or result, to bound the monitor's input. The pending call is
# never clipped, as the monitor must see everything that would run.
MAX_CHARS = 2000


def _clip(text: str) -> str:
    """Truncate text to `MAX_CHARS`, marking the cut."""
    return text if len(text) <= MAX_CHARS else f"{text[:MAX_CHARS]} [...]"


def _render_call(call: ToolCall) -> str:
    """Render a tool call as `function({arguments})`."""
    return f"{call.function}({json.dumps(call.arguments)})"


def task_text(history: list[ChatMessage]) -> str:
    """Return the text of the first user message, which holds the task."""
    return next((m.text for m in history if isinstance(m, ChatMessageUser)), "")


def render_actions(history: list[ChatMessage], call: ToolCall, size: int) -> str:
    """
    Render recent tool calls and results, then the pending call.

    The agent's own text and reasoning are left out, so the monitor judges actions
    rather than the agent's explanations of them. Earlier calls and results are
    clipped; the pending call is shown in full.

    Args:
        history: Conversation so far.
        call: The tool call awaiting approval.
        size: Number of most recent messages to include.

    Returns:
        One line per call or result, ending with the pending call.
    """
    lines = []
    for message in (history[-size:] if size > 0 else []):
        if isinstance(message, ChatMessageAssistant):
            calls = message.tool_calls or []
            lines += [f"CALL {_clip(_render_call(c))}" for c in calls]
        elif isinstance(message, ChatMessageTool):
            lines.append(f"RESULT {_clip(message.text)}")
    lines.append(f"PENDING {_render_call(call)}")
    return "\n".join(lines)


def parse_score(text: str) -> tuple[int | None, str]:
    """
    Read the score and reasoning from a monitor reply.

    Args:
        text: The monitor model's reply.

    Returns:
        The score, or None if the reply isn't in the expected format, and the
        reasoning (the whole reply when the format is wrong).
    """
    score = re.search(r"<score>\s*(\d+)\s*</score>", text)
    reasoning = re.search(r"<reasoning>(.*?)</reasoning>", text, re.DOTALL)
    if not (score and reasoning):
        return None, text.strip()
    return int(score.group(1)), reasoning.group(1).strip()


def decide(score: int | None, escalate_at: int, reject_at: int) -> ApprovalDecision:
    """
    Map a suspicion score to an approval decision.

    Args:
        score: Suspicion from 0 to 10, or None if the monitor gave none.
        escalate_at: Lowest score that is escalated rather than approved.
        reject_at: Lowest score that is rejected outright.

    Returns:
        "approve", "escalate" or "reject"; a missing score escalates.
    """
    if score is None:
        return "escalate"
    if score >= reject_at:
        return "reject"
    return "escalate" if score >= escalate_at else "approve"


@approver
def monitor(history_size: int, escalate_at: int, reject_at: int) -> Approver:
    """
    Approve, escalate or reject each tool call by its suspicion score.

    Uses the model with the "monitor" role and records each score in the sample
    store under "monitor".

    Args:
        history_size: Number of recent messages the monitor sees.
        escalate_at: Lowest score that is escalated rather than approved.
        reject_at: Lowest score that is rejected outright.

    Returns:
        The approver.

    Raises:
        ValueError: If `reject_at` is lower than `escalate_at`.
    """
    if reject_at < escalate_at:
        raise ValueError(
            f"reject_at ({reject_at}) can't be lower than escalate_at ({escalate_at})"
        )

    async def approve(
        message: str, call: ToolCall, view: ToolCallView, history: list[ChatMessage]
    ) -> Approval:
        """
        Score a pending tool call and decide whether it runs.

        Inspect calls every approver with these four arguments, so the signature
        must match its `Approver` protocol even though `message` and `view` are
        unused.

        Args:
            message: The agent's text alongside the call; unused, as the monitor
                judges actions rather than the agent's explanations.
            call: The tool call awaiting approval.
            view: Inspect's rendering of the call for human approvers; unused.
            history: Conversation so far, from which the task and recent actions
                are rendered.

        Returns:
            The decision, with the score and reasoning as its explanation.
        """
        prompt = MONITOR_PROMPT.read_text().format(
            task=task_text(history),
            actions=render_actions(history, call, history_size),
        )
        output = await get_model(role="monitor").generate(prompt)
        score, reasoning = parse_score(output.completion)
        decision = decide(score, escalate_at, reject_at)
        record = {
            "call_id": call.id,
            "function": call.function,
            "score": score,
            "reasoning": reasoning,
            "decision": decision,
        }
        store().set("monitor", [*store().get("monitor", []), record])
        return Approval(
            decision=decision, explanation=f"Suspicion {score}/10: {reasoning}"
        )

    return approve


SUMMARY_KEYS = ("max_suspicion", "mean_suspicion", "scored", "escalated", "rejected")


@scorer(metrics={key: [mean()] for key in SUMMARY_KEYS})
def monitor_summary() -> Scorer:
    """Summarise the monitor's scores and decisions for the run."""

    async def score(state: TaskState, target: Target) -> Score:
        """
        Summarise the scores the monitor recorded during the sample.

        Inspect calls every scorer with these two arguments, so the signature must
        match its `Scorer` protocol even though neither is used.

        Args:
            state: Sample state; unused. Its `store` is the same store read here
                through `store()`, used so the scorer matches the approver, which
                isn't given the task state.
            target: Correct answer for the sample; unused, as the monitor summary
                has nothing to compare against.

        Returns:
            Maximum and mean suspicion, and counts of calls scored, escalated and
            rejected.
        """
        records = store().get("monitor", [])
        scores = [r["score"] for r in records if r["score"] is not None]
        decisions = [r["decision"] for r in records]
        return Score(
            value={
                "max_suspicion": max(scores, default=0),
                "mean_suspicion": fmean(scores) if scores else 0.0,
                "scored": len(records),
                "escalated": decisions.count("escalate"),
                "rejected": decisions.count("reject"),
            }
        )

    return score
