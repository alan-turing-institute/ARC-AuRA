"""
Turn the task into one research idea, with literature search.

Adapted from AI Scientist-v2's `ai_scientist/perform_ideation_temp_free.py`; see
LICENSE. The task takes the place of upstream's workshop description, and only one
idea is generated.

`cfg` keys used here: "model", "timeout" and "num_reflections" (the most rounds before
the idea must be finalised).
"""

import json

from ai_scientist_v2 import prompts, tools
from ai_scientist_v2.literature import get_paper, search_papers
from ai_scientist_v2.llm import call_tool, query
from ai_scientist_v2.nodes import emit


def generate_idea(prompt: str, cfg: dict) -> tuple[dict, list[dict]]:
    """
    Develop one research idea for the task, searching the literature between rounds.

    Every round but the last may search or finalise; the last must finalise.

    Args:
        prompt: The task prompt the loop was started with.
        cfg: Uses "model", "timeout" and "num_reflections".

    Returns:
        The idea, with the fields in `tools.IDEA_FIELDS`, "Metric" and "Papers", and
        the papers it relies on, with their abstracts. Papers the searches didn't
        return are left out.
    """
    model, rounds = cfg["model"], cfg["num_reflections"]
    system = prompts.IDEA_SYSTEM.format(timeout=cfg["timeout"])
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": prompts.IDEA_TASK.format(prompt=prompt)},
    ]
    seen = {}
    for round_num in range(1, rounds):
        message = query(
            model, messages, [tools.SEARCH_PAPERS, tools.FINALIZE_IDEA], "auto"
        )
        messages.append(message.model_dump(exclude_none=True))
        for call in message.tool_calls or []:
            arguments = json.loads(call.function.arguments)
            if call.function.name == "finalize_idea":
                return _finalised(arguments, round_num, seen)
            papers, content = _search(arguments["query"])
            seen |= {p["paper_id"]: p for p in papers}
            emit("idea_search", query=arguments["query"], results=len(papers))
            messages.append(
                {"role": "tool", "tool_call_id": call.id, "content": content}
            )
        reflection = prompts.IDEA_REFLECTION.format(round=round_num + 1, rounds=rounds)
        messages.append({"role": "user", "content": reflection})
    return _finalised(call_tool(model, messages, tools.FINALIZE_IDEA), rounds, seen)


def _search(query: str) -> tuple[list[dict], str]:
    """
    Search the literature, passing a failure back to the model as upstream does.

    Args:
        query: The model's search query.

    Returns:
        The papers found, and the tool message's content: the papers as JSON, or the
        error if the search failed (e.g. Semantic Scholar's rate limit).
    """
    try:
        papers = search_papers(query)
    except RuntimeError as e:
        emit("search_error", query=query, error=str(e))
        return [], f"Error using tool search_papers: {e}"
    return papers, json.dumps(papers)


def _with_abstract(paper: dict) -> dict:
    """The paper from `get_paper`, with its abstract, or as searched if that fails."""
    try:
        return get_paper(paper["paper_id"])
    except RuntimeError as e:
        emit("search_error", paper_id=paper["paper_id"], error=str(e))
        return paper


def _finalised(
    arguments: dict, round_num: int, seen: dict[str, dict]
) -> tuple[dict, list[dict]]:
    """Emit the idea's event; return it with the papers it cites that were seen."""
    idea = {tools.IDEA_KEYS.get(key, key): value for key, value in arguments.items()}
    emit("idea", round=round_num, **idea)
    return idea, [_with_abstract(seen[pid]) for pid in idea["Papers"] if pid in seen]
