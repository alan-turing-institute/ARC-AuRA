"""
Turn the task into one research idea, with literature search.

Prompts and the idea's fields are adapted from AI Scientist-v2's
`ai_scientist/perform_ideation_temp_free.py`; see LICENSE. The task takes the place of
upstream's workshop description, and only one idea is generated.

`cfg` keys used here: "model", "timeout" and "num_reflections" (the most rounds before
the idea must be finalised).
"""

import json

from ai_scientist_v2.literature import get_paper, search_papers
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

# Tool properties can't contain spaces, so the tool uses snake_case names
_KEYS = {name.lower().replace(" ", "_"): name for name in _FIELDS}

_FINALIZE_TOOL = {
    "type": "function",
    "function": {
        "name": "finalize_idea",
        "description": "Finalise your idea by providing its details.",
        "parameters": {
            "type": "object",
            "properties": {
                **{
                    key: {"type": "string", "description": _FIELDS[name]}
                    for key, name in _KEYS.items()
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
            "required": [*_KEYS, "Metric", "Papers"],
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


_TASK_PROMPT = (
    "{prompt}\n\n"
    "Propose a research idea for this task. If it already includes research "
    "questions or a literature review, build on them rather than redoing them."
)


def generate_idea(prompt: str, cfg: dict) -> tuple[dict, list[dict]]:
    """
    Develop one research idea for the task, searching the literature between rounds.

    Every round but the last may search or finalise; the last must finalise.

    Args:
        prompt: The task prompt the loop was started with.
        cfg: Uses "model", "timeout" and "num_reflections".

    Returns:
        The idea, with the fields in `_FIELDS`, "Metric" and "Papers", and the papers
        it relies on, with their abstracts. Papers the searches didn't return are
        left out.
    """
    model, rounds = cfg["model"], cfg["num_reflections"]
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT.format(timeout=cfg["timeout"])},
        {"role": "user", "content": _TASK_PROMPT.format(prompt=prompt)},
    ]
    seen = set()
    for round_num in range(1, rounds):
        message = query(model, messages, [_SEARCH_TOOL, _FINALIZE_TOOL], "auto")
        messages.append(message.model_dump(exclude_none=True))
        for call in message.tool_calls or []:
            arguments = json.loads(call.function.arguments)
            if call.function.name == "finalize_idea":
                return _finalised(arguments, round_num, seen)
            papers = search_papers(arguments["query"])
            seen |= {p["paper_id"] for p in papers}
            emit("idea_search", query=arguments["query"], results=len(papers))
            messages.append(_tool_result(call.id, papers))
        reflection = _REFLECTION_PROMPT.format(round=round_num + 1, rounds=rounds)
        messages.append({"role": "user", "content": reflection})
    return _finalised(call_tool(model, messages, _FINALIZE_TOOL), rounds, seen)


def _tool_result(call_id: str, papers: list[dict]) -> dict:
    """A tool message holding search results, as JSON."""
    return {"role": "tool", "tool_call_id": call_id, "content": json.dumps(papers)}


def _finalised(
    arguments: dict, round_num: int, seen: set[str]
) -> tuple[dict, list[dict]]:
    """Emit the idea's event; return it with the papers it cites that were seen."""
    idea = {_KEYS.get(key, key): value for key, value in arguments.items()}
    emit("idea", round=round_num, **idea)
    return idea, [get_paper(pid) for pid in idea["Papers"] if pid in seen]
