"""
The five ways the search makes a node: draft, debug, improve, tune and ablate.

Adapted from AI Scientist-v2's `ai_scientist/treesearch/parallel_agent.py`; see
LICENSE. Each operator is one model call that returns a plan and a complete script.
"""

from ai_scientist_v2 import prompts, tools
from ai_scientist_v2.llm import call_tool
from ai_scientist_v2.nodes import Node


def stage_brief(idea: dict, stage: str, timeout: int) -> str:
    """
    Build the part of every operator prompt that stays fixed within a stage.

    Args:
        idea: The research idea, from `finalize_idea`, including its "Metric".
        stage: Key of `prompts.STAGE_GOALS`.
        timeout: Script timeout, in seconds.

    Returns:
        The research idea, the stage's goals and the implementation guidelines.
    """
    research_idea = prompts.RESEARCH_IDEA.format(
        title=idea["Title"],
        abstract=idea["Abstract"],
        hypothesis=idea["Short Hypothesis"],
        experiments=idea["Experiments"],
    )
    guideline = prompts.IMPLEMENTATION_GUIDELINE.format(
        timeout=timeout, metric=idea["Metric"]["name"]
    )
    return _sections(
        ("Your research idea", research_idea),
        ("Current stage", f"{stage}\n{prompts.STAGE_GOALS[stage]}"),
        ("Implementation guideline", guideline),
    )


def draft(model: str, brief: str, memory: str) -> tuple[str, str]:
    """
    Write a first, simple implementation of the idea.

    Args:
        model: Model name as configured in the LiteLLM gateway.
        brief: From `stage_brief`.
        memory: From `summarise_journal`.

    Returns:
        The plan and the script.
    """
    prompt = _sections(
        ("Introduction", prompts.DRAFT_INTRO),
        ("Brief", brief),
        ("Memory", memory),
        ("Experiment design sketch guideline", prompts.DRAFT_GUIDELINE),
    )
    return _ask(model, prompt)


def debug(model: str, brief: str, parent: Node) -> tuple[str, str]:
    """
    Fix a buggy node, given its code, output and review.

    Args:
        model: Model name as configured in the LiteLLM gateway.
        brief: From `stage_brief`.
        parent: The buggy node.

    Returns:
        The plan and the fixed script.
    """
    prompt = _sections(
        ("Introduction", prompts.DEBUG_INTRO),
        ("Brief", brief),
        ("Previous (buggy) implementation", _code(parent.code)),
        ("Execution output", _code(parent.output, "")),
        ("Review", parent.summary),
        ("Feedback based on generated plots", parent.plot_feedback),
        ("Bugfix sketch guideline", prompts.DEBUG_GUIDELINE),
    )
    return _ask(model, prompt)


def improve(model: str, brief: str, memory: str, parent: Node) -> tuple[str, str]:
    """
    Change a working node to do better, following the stage's goals.

    Args:
        model: Model name as configured in the LiteLLM gateway.
        brief: From `stage_brief`.
        memory: From `summarise_journal`.
        parent: The working node to build on.

    Returns:
        The plan and the improved script.
    """
    prompt = _sections(
        ("Introduction", prompts.IMPROVE_INTRO),
        ("Brief", brief),
        ("Memory", memory),
        ("Previous solution", _code(parent.code)),
        ("Its results", f"Metric: {parent.metric}\n{parent.summary}"),
        ("Feedback based on generated plots", parent.plot_feedback),
        ("Response guideline", prompts.IMPROVE_GUIDELINE),
    )
    return _ask(model, prompt)


def tune(model: str, brief: str, parent: Node, tried: list[str]) -> tuple[str, str]:
    """
    Change one setting of a working node, different from those already tried.

    Args:
        model: Model name as configured in the LiteLLM gateway.
        brief: From `stage_brief`.
        parent: The working node to tune.
        tried: Names of settings already changed in this stage.

    Returns:
        The plan, starting "Setting: <name>", and the script.
    """
    prompt = _sections(
        ("Introduction", prompts.TUNE_INTRO),
        ("Brief", brief),
        ("Base code you are working on", _code(parent.code)),
        ("Previous attempts", _tried(tried)),
        ("Requirements", prompts.TUNE_REQUIREMENTS),
    )
    return _ask_change(model, prompt, "Setting")


def ablate(model: str, brief: str, parent: Node, tried: list[str]) -> tuple[str, str]:
    """
    Remove or vary one part of a working node's approach, to measure its effect.

    Args:
        model: Model name as configured in the LiteLLM gateway.
        brief: From `stage_brief`.
        parent: The working node to ablate.
        tried: Names of ablations already run in this stage.

    Returns:
        The plan, starting "Ablation: <name>", and the script.
    """
    prompt = _sections(
        ("Introduction", prompts.ABLATE_INTRO),
        ("Brief", brief),
        ("Base code you are working on", _code(parent.code)),
        ("Previous ablations", _tried(tried)),
        ("Requirements", prompts.ABLATE_REQUIREMENTS),
    )
    return _ask_change(model, prompt, "Ablation")


def _sections(*sections: tuple[str, str | None]) -> str:
    """Join (heading, text) pairs into a markdown prompt, skipping empty ones."""
    return "\n\n".join(f"## {head}\n{text}" for head, text in sections if text)


def _code(text: str, lang: str = "python") -> str:
    """Wrap text in a markdown code block."""
    return f"```{lang}\n{text}\n```"


def _tried(tried: list[str]) -> str:
    """List what has been tried, or say nothing has."""
    return "\n".join(f"- {t}" for t in tried) or "Nothing has been tried yet."


def _ask(model: str, prompt: str) -> tuple[str, str]:
    """Ask for a plan and script with `submit_code`."""
    reply = call_tool(model, [{"role": "user", "content": prompt}], tools.SUBMIT_CODE)
    return reply["plan"], reply["code"]


def _ask_change(model: str, prompt: str, kind: str) -> tuple[str, str]:
    """Ask for a named change; put its name on the plan's first line."""
    reply = call_tool(model, [{"role": "user", "content": prompt}], tools.SUBMIT_CHANGE)
    return f"{kind}: {reply['name']}\n{reply['plan']}", reply["code"]
