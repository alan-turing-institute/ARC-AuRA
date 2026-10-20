"""
The five ways the search makes a node: draft, debug, improve, tune and ablate.

Prompts are adapted from AI Scientist-v2's `ai_scientist/treesearch/parallel_agent.py`
and `agent_manager.py` (see LICENSE), without the GPU, PyTorch and HuggingFace
requirements, generalised from training ML models to any computational research
(experiments, analyses, simulations), and with our `metrics.json` contract. Each
operator is one model call that returns a plan and a complete script.
"""

from ai_scientist_v2.llm import call_tool
from ai_scientist_v2.nodes import Node

# In stage order; generalised from upstream's `main_stage_goals`, with data offline
STAGE_GOALS = {
    "initial_implementation": (
        "- Get a basic, working first version of the experiment, analysis or "
        "simulation\n"
        "- Keep it simple: one dataset, model or setting\n"
        "- Aim for correctness before anything else"
    ),
    "baseline_tuning": (
        "- Refine the settings of the current approach so its results are better or "
        "more reliable, e.g. sample sizes, iterations, parameters, thresholds or "
        "preprocessing choices\n"
        "- DO NOT change the approach itself from the previous stage\n"
        "- Where it makes sense, check that the results hold on other data or settings"
    ),
    "creative_research": (
        "- Explore novel improvements or extensions of the approach\n"
        "- Come up with experiments or analyses that reveal new insights\n"
        "- Be creative and think outside the box"
    ),
    "ablation_studies": (
        "- Find out which parts of the approach matter: remove or vary one component, "
        "assumption or choice at a time and measure its effect on the results\n"
        "- Keep the data and everything else as in the previous stage"
    ),
}

_SUBMIT_CODE = {
    "type": "function",
    "function": {
        "name": "submit_code",
        "description": "Submit a plan and the complete experiment script.",
        "parameters": {
            "type": "object",
            "properties": {
                "plan": {
                    "type": "string",
                    "description": "Outline of the solution in natural language.",
                },
                "code": {
                    "type": "string",
                    "description": "The complete, self-contained Python script.",
                },
            },
            "required": ["plan", "code"],
        },
    },
}

# For tune and ablate, which also name the change so later calls can avoid repeats
_SUBMIT_CHANGE = {
    "type": "function",
    "function": {
        "name": "submit_change",
        "description": "Submit a named change, its plan and the complete script.",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Short name of the change, e.g. 'sample size'.",
                },
                **_SUBMIT_CODE["function"]["parameters"]["properties"],
            },
            "required": ["name", "plan", "code"],
        },
    },
}


def stage_brief(idea: dict, stage: str, timeout: int) -> str:
    """
    Build the part of every operator prompt that stays fixed within a stage.

    Args:
        idea: The research idea, from `finalize_idea`, including its "Metric".
        stage: Key of `STAGE_GOALS`.
        timeout: Script timeout, in seconds.

    Returns:
        The research idea, the stage's goals and the implementation guidelines.
    """
    metric = idea["Metric"]["name"]
    return _sections(
        (
            "Your research idea",
            "You are an ambitious researcher who is looking to publish a paper that "
            "will contribute significantly to the field. You have an idea and you "
            "want to carry out computational experiments or analyses to gain "
            "scientific insights.\n\n"
            f"Title: {idea['Title']}\n"
            f"Abstract: {idea['Abstract']}\n"
            f"Short Hypothesis: {idea['Short Hypothesis']}\n"
            f"Experiments: {idea['Experiments']}",
        ),
        ("Current stage", f"{stage}\n{STAGE_GOALS[stage]}"),
        (
            "Implementation guideline",
            "- The code must be a single, self-contained Python script that runs "
            "as-is from top to bottom. Don't put code in an "
            "`if __name__ == '__main__':` block, and don't skip any parts.\n"
            "- It runs on CPU only, with no internet access: nothing can be "
            "downloaded or installed.\n"
            "- Available packages: numpy, pandas, scikit-learn, scipy and "
            "matplotlib.\n"
            "- Use only data the script can create or that is already installed: "
            "simulated or synthetic data, or datasets bundled with installed "
            "packages (e.g. scikit-learn's `load_*` datasets). Don't use functions "
            "that download data, such as scikit-learn's `fetch_*`.\n"
            f"- It must finish within {timeout} seconds.\n"
            "- The script runs in its own empty folder. Write all files there.\n"
            f"- Print the results, including `{metric}`.\n"
            f"- At the end, write `metrics.json` with the metric as a top-level "
            f'number: `{{"{metric}": value}}`. If the script runs several settings, '
            "use the value for the main one; other results can go under other "
            "keys.\n"
            "- Save plots as PNG files with distinct, descriptive names.",
        ),
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
        (
            "Introduction",
            "Your first task is to write Python code for a solid first version of "
            "the experiment or analysis in your research idea, from preparing the "
            "data to computing and visualising the results. Focus on getting a "
            "simple but working implementation "
            "first, before any sophisticated improvements. We will explore more "
            "advanced variations in later stages.",
        ),
        ("Brief", brief),
        ("Memory", memory),
        (
            "Experiment design sketch guideline",
            "- This first design should be relatively simple, without extensive "
            "tuning of its settings.\n"
            "- Take the Memory section into consideration.\n"
            "- The plan should be 6-10 sentences.\n"
            "- Don't suggest exploratory data analysis.\n"
            "- Create synthetic data if needed.",
        ),
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
        (
            "Introduction",
            "You are an experienced researcher. Your previous code for the "
            "research experiment had a bug, so based on the information below, you "
            "should revise it in order to fix this bug.",
        ),
        ("Brief", brief),
        ("Previous (buggy) implementation", _code(parent.code)),
        ("Execution output", _code(parent.output, "")),
        ("Review", parent.summary),
        ("Feedback based on generated plots", parent.plot_feedback),
        (
            "Bugfix sketch guideline",
            "- The plan should be 3-5 sentences on how to fix the issue.\n"
            "- Don't suggest exploratory data analysis.\n"
            "- Submit the complete code, including the parts that didn't change.",
        ),
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
        (
            "Introduction",
            "You are an experienced researcher. You are provided with a previously "
            "developed implementation. Your task is to improve it based on the "
            "current experimental stage.",
        ),
        ("Brief", brief),
        ("Memory", memory),
        ("Previous solution", _code(parent.code)),
        ("Its results", f"Metric: {parent.metric}\n{parent.summary}"),
        ("Feedback based on generated plots", parent.plot_feedback),
        (
            "Response guideline",
            "- The plan should be 7-10 sentences.\n"
            "- Submit the complete code, including the parts that didn't change.",
        ),
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
        (
            "Introduction",
            "You are a researcher refining the settings of a first experiment or "
            "analysis. Based on the current implementation and previous attempts, "
            "propose and implement ONE change to a setting, such as a sample size, "
            "number of iterations, parameter, threshold or preprocessing choice, to "
            "see if it makes the results better or more reliable. Start with the "
            "settings most likely to matter.",
        ),
        ("Brief", brief),
        ("Base code you are working on", _code(parent.code)),
        ("Previous attempts", _tried(tried)),
        (
            "Requirements",
            "- Change ONE specific setting, different from previous attempts.\n"
            "- The plan should be 3-5 sentences on what is changed and why.\n"
            "- Submit the complete code, including the parts that didn't change.",
        ),
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
        (
            "Introduction",
            "You are a researcher finding out which parts of your approach matter, "
            "with an ablation or sensitivity study. Based on the current "
            "implementation and previous ablations, propose and implement ONE new "
            "ablation that removes or varies a different component, assumption or "
            "choice.",
        ),
        ("Brief", brief),
        ("Base code you are working on", _code(parent.code)),
        ("Previous ablations", _tried(tried)),
        (
            "Requirements",
            "- Ablate ONE specific component, assumption or choice.\n"
            "- It must be a new idea, not a variation of previous ablations.\n"
            "- If only one dataset or setting has been used so far, one ablation "
            "should use several (at least 3) different ones.\n"
            "- The plan should be 3-5 sentences on what is ablated and why.\n"
            "- Submit the complete code, including the parts that didn't change.",
        ),
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
    reply = call_tool(model, [{"role": "user", "content": prompt}], _SUBMIT_CODE)
    return reply["plan"], reply["code"]


def _ask_change(model: str, prompt: str, kind: str) -> tuple[str, str]:
    """Ask for a named change; put its name on the plan's first line."""
    reply = call_tool(model, [{"role": "user", "content": prompt}], _SUBMIT_CHANGE)
    return f"{kind}: {reply['name']}\n{reply['plan']}", reply["code"]
