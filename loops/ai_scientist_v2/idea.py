"""
Turn the task into one research idea, with literature search.

Prompts and the idea's fields are adapted from AI Scientist-v2's
`ai_scientist/perform_ideation_temp_free.py`; see LICENSE. The task takes the place of
upstream's workshop description, and only one idea is generated.

`cfg` keys used here: "model", "timeout" and "num_reflections" (the most rounds before
the idea must be finalised).
"""

import json

from ai_scientist_v2.literature import search_papers
from ai_scientist_v2.llm import call_tool, query
from ai_scientist_v2.nodes import emit

_SEARCH_TOOL = {
    "type": "function",
    "function": {
        "name": "search_papers",
        "description": "Search the literature for papers, to find related work and "
        "check the idea is novel.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "The search query."},
            },
            "required": ["query"],
        },
    },
}

_FIELDS = {
    "Title": "A catchy and informative title for the proposal.",
    "Short Hypothesis": "A concise statement of the main hypothesis or research "
    "question. Clarify the need for this direction, that this is the best setting "
    "to investigate it, and that there are no obviously simpler ways to answer it.",
    "Related Work": "A brief discussion of the most relevant related work and how "
    "the proposal clearly differs from it, and is not a trivial extension.",
    "Abstract": "An abstract that summarises the proposal in conference format "
    "(approximately 250 words).",
    "Experiments": "The experiments or analyses that would test the hypothesis. "
    "Make them simple and feasible, and be specific about exactly how they test it.",
    "Risk Factors and Limitations": "Potential risks and limitations of the proposal.",
}

_FINALIZE_TOOL = {
    "type": "function",
    "function": {
        "name": "finalize_idea",
        "description": "Finalise your idea by providing its details.",
        "parameters": {
            "type": "object",
            "properties": {
                **{
                    name: {"type": "string", "description": text}
                    for name, text in _FIELDS.items()
                },
                "Metric": {
                    "type": "object",
                    "description": "The single number the experiments are judged "
                    "by, which each script writes to `metrics.json`.",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "Short snake_case name, e.g. 'accuracy'.",
                        },
                        "higher_is_better": {"type": "boolean"},
                    },
                    "required": ["name", "higher_is_better"],
                },
                "Papers": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "The paper_ids of the papers the idea relies on.",
                },
            },
            "required": [*_FIELDS, "Metric", "Papers"],
        },
    },
}

_SYSTEM_PROMPT = (
    "You are an experienced researcher who aims to propose high-impact research "
    "ideas resembling exciting grant proposals. Feel free to propose any novel ideas "
    "or experiments; make sure they are novel. Be very creative and think out of the "
    "box. Each proposal should stem from a simple and elegant question, observation "
    "or hypothesis about the topic. For example, they could involve very interesting "
    "and simple interventions or investigations that explore new possibilities or "
    "challenge existing assumptions. Clearly explain how the proposal differs from "
    "the existing literature.\n\n"
    "The experiments must be computational and run on a CPU within {timeout} "
    "seconds each, with no internet access, using numpy, pandas, scikit-learn, "
    "scipy and matplotlib, and only synthetic data or datasets bundled with those "
    "packages.\n\n"
    "Use `search_papers` to search the literature, and `finalize_idea` when the "
    "idea is ready. Search at least once before finalising, so the idea is "
    "well-informed by existing research."
)

_REFLECTION_PROMPT = (
    "Round {round}/{rounds}.\n\n"
    "In your thoughts, first carefully consider the quality, novelty and feasibility "
    "of the proposal so far, and any other factors you think are important. Keep it "
    "clear and concise, and don't make things overly complicated. Then refine and "
    "improve the proposal, sticking to the spirit of the original idea unless there "
    "are glaring issues. Incorporate any new results from your searches."
)


def generate_idea(prompt: str, cfg: dict) -> dict:
    """
    Develop one research idea for the task, searching the literature between rounds.

    Every round but the last may search or finalise; the last must finalise.

    Args:
        prompt: The task prompt the loop was started with.
        cfg: Uses "model", "timeout" and "num_reflections".

    Returns:
        The idea, with the fields of `_FINALIZE_TOOL`.
    """
    model, rounds = cfg["model"], cfg["num_reflections"]
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT.format(timeout=cfg["timeout"])},
        {"role": "user", "content": f"{prompt}\n\nPropose a research idea for this."},
    ]
    for round_num in range(1, rounds):
        message = query(model, messages, [_SEARCH_TOOL, _FINALIZE_TOOL], "auto")
        messages.append(message.model_dump(exclude_none=True))
        for call in message.tool_calls or []:
            arguments = json.loads(call.function.arguments)
            if call.function.name == "finalize_idea":
                return _finalised(arguments, round_num)
            papers = search_papers(arguments["query"])
            emit("idea_search", query=arguments["query"], results=len(papers))
            messages.append(_tool_result(call.id, papers))
        reflection = _REFLECTION_PROMPT.format(round=round_num + 1, rounds=rounds)
        messages.append({"role": "user", "content": reflection})
    return _finalised(call_tool(model, messages, _FINALIZE_TOOL), rounds)


def _tool_result(call_id: str, papers: list[dict]) -> dict:
    """A tool message holding search results, as JSON."""
    return {"role": "tool", "tool_call_id": call_id, "content": json.dumps(papers)}


def _finalised(idea: dict, round_num: int) -> dict:
    """Emit the finalised idea's event, and return the idea."""
    emit("idea", round=round_num, **idea)
    return idea
