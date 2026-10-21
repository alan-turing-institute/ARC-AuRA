"""
Every tool the model is asked to call, in OpenAI function format.

Adapted from AI Scientist-v2 (see LICENSE). Tools are used for structured replies:
apart from `search_papers`, calling one only returns its arguments to the loop.
"""


def _function(name: str, description: str, properties: dict, required: list) -> dict:
    """A tool definition, from its name, description and parameters."""
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        },
    }


def _string(description: str) -> dict:
    """A string parameter."""
    return {"type": "string", "description": description}


def _boolean(description: str) -> dict:
    """A boolean parameter."""
    return {"type": "boolean", "description": description}


# Idea: `ai_scientist/perform_ideation_temp_free.py`. Metric and Papers are ours.
SEARCH_PAPERS = _function(
    "search_papers",
    "Search the literature for papers, to find related work and check the idea is "
    "novel.",
    {"query": _string("The search query.")},
    ["query"],
)

IDEA_FIELDS = {
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
IDEA_KEYS = {name.lower().replace(" ", "_"): name for name in IDEA_FIELDS}

FINALIZE_IDEA = _function(
    "finalize_idea",
    "Finalise your idea by providing its details.",
    {
        **{key: _string(IDEA_FIELDS[name]) for key, name in IDEA_KEYS.items()},
        "Metric": {
            "type": "object",
            "description": "The single number the experiments are judged by, which "
            "each script writes to `metrics.json`.",
            "properties": {
                "name": _string("Short snake_case name, e.g. 'accuracy'."),
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
    [*IDEA_KEYS, "Metric", "Papers"],
)

# Operators: `ai_scientist/treesearch/parallel_agent.py`
_PLAN_AND_CODE = {
    "plan": _string("Outline of the solution in natural language."),
    "code": _string("The complete, self-contained Python script."),
}

SUBMIT_CODE = _function(
    "submit_code",
    "Submit a plan and the complete experiment script.",
    _PLAN_AND_CODE,
    ["plan", "code"],
)

# Ours, for tune and ablate, which name the change so later calls can avoid repeats
SUBMIT_CHANGE = _function(
    "submit_change",
    "Submit a named change, its plan and the complete script.",
    {
        "name": _string("Short name of the change, e.g. 'sample size'."),
        **_PLAN_AND_CODE,
    },
    ["name", "plan", "code"],
)

# Node review: `ai_scientist/treesearch/parallel_agent.py`
SUBMIT_REVIEW = _function(
    "submit_review",
    "Submit a review of the experiment script's output.",
    {
        "is_bug": _boolean(
            "true if the output shows that the execution failed or has some bug, "
            "otherwise false."
        ),
        "summary": _string(
            "If there is a bug, summarise it and propose a fix. Otherwise, summarise "
            "the main findings."
        ),
    },
    ["is_bug", "summary"],
)

ANALYZE_PLOTS = _function(
    "analyze_experiment_plots",
    "Analyse experimental plots and give feedback on the results.",
    {
        "feedback": _string(
            "What the plots show, whether they are meaningful, and what they imply "
            "for the experiment."
        ),
    },
    ["feedback"],
)

# Best node and stage completion: `ai_scientist/treesearch/agent_manager.py`
SELECT_BEST = _function(
    "select_best_implementation",
    "Select the best implementation based on all the evidence.",
    {
        "selected_id": _string("ID of the selected best implementation."),
        "reasoning": _string("Why this implementation was chosen."),
    },
    ["selected_id", "reasoning"],
)

STAGE_DONE = _function(
    "evaluate_stage_completion",
    "Evaluate whether the current stage is complete.",
    {
        "is_complete": _boolean("Whether the current stage is complete."),
        "reasoning": _string("Reasoning for the decision."),
    },
    ["is_complete", "reasoning"],
)

# Citations: `ai_scientist/perform_icbinb_writeup.py` (`get_citation_addition`),
# split into two calls, since the search runs between them
FIND_CITATION = _function(
    "find_citation",
    "Name the most important citation still missing, or stop.",
    {
        "done": _boolean("true if no more citations are needed."),
        "description": _string(
            "The purpose of the citation, and what you are looking for. Empty if done."
        ),
        "query": _string(
            "The search query to find the paper, e.g. 'attention is all you need'. "
            "Empty if done."
        ),
    },
    ["done", "description", "query"],
)

SELECT_CITATIONS = _function(
    "select_citations",
    "Select the search results to cite, possibly none.",
    {
        "indices": {
            "type": "array",
            "items": {"type": "integer"},
            "description": "Indices of the selected papers, e.g. [0, 1].",
        },
        "description": _string(
            "A brief description of the selected work(s), their relevance, and where "
            "in the report to cite them."
        ),
    },
    ["indices", "description"],
)
