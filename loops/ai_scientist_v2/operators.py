"""
The five ways the search makes a node: draft, debug, improve, tune and ablate.

Prompts are adapted from AI Scientist-v2's `ai_scientist/treesearch/parallel_agent.py`
and `agent_manager.py` (see LICENSE), without the GPU, PyTorch and HuggingFace
requirements and with our `metrics.json` contract. Each operator is one model call that
returns a plan and a complete script.
"""

from ai_scientist_v2.llm import call_tool
from ai_scientist_v2.nodes import Node

# In stage order; from upstream's `main_stage_goals`, with datasets kept offline
STAGE_GOALS = {
    "initial_implementation": (
        "- Focus on getting a basic working implementation\n"
        "- Use a simple dataset\n"
        "- Aim for basic functional correctness"
    ),
    "baseline_tuning": (
        "- Change hyperparameters such as the number of iterations, learning rate or "
        "regularisation to improve performance\n"
        "- DO NOT change the method or model from the previous stage\n"
        "- Where it makes sense, also test on more datasets: scikit-learn's bundled "
        "datasets or synthetic data"
    ),
    "creative_research": (
        "- Explore novel improvements\n"
        "- Come up with experiments to reveal new insights\n"
        "- Be creative and think outside the box"
    ),
    "ablation_studies": (
        "- Conduct systematic component analysis that reveals the contribution of each "
        "part\n"
        "- Use the same datasets as the previous stage"
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
                    "description": "Short name of the change, e.g. 'learning rate'.",
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
            "You are an ambitious AI researcher who is looking to publish a paper "
            "that will contribute significantly to the field. You have an idea and "
            "you want to conduct creative experiments to gain scientific insights.\n\n"
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
            "- For data, use scikit-learn's bundled datasets (e.g. `load_digits`, "
            "`load_iris`, `load_wine`, `load_breast_cancer`) or synthetic data. "
            "Don't use `fetch_*` functions, which download.\n"
            f"- It must finish within {timeout} seconds.\n"
            "- The script runs in its own empty folder. Write all files there.\n"
            "- Print the results, including the evaluation metric.\n"
            f"- At the end, write `metrics.json` with the metric as a number: "
            f'`{{"{metric}": value}}`.\n'
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
            "Your first task is to write Python code to implement a solid baseline "
            "based on your research idea, from data preparation to evaluation and "
            "visualisation. Focus on getting a simple but working implementation "
            "first, before any sophisticated improvements. We will explore more "
            "advanced variations in later stages.",
        ),
        ("Brief", brief),
        ("Memory", memory),
        (
            "Experiment design sketch guideline",
            "- This first design should be relatively simple, without extensive "
            "hyperparameter optimisation.\n"
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
            "You are an experienced AI researcher. Your previous code for the "
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
            "You are an experienced AI researcher. You are provided with a previously "
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
    Tune one hyperparameter of a working node, different from those already tried.

    Args:
        model: Model name as configured in the LiteLLM gateway.
        brief: From `stage_brief`.
        parent: The working node to tune.
        tried: Names of hyperparameters already tuned in this stage.

    Returns:
        The plan, starting "Hyperparameter: <name>", and the script.
    """
    prompt = _sections(
        (
            "Introduction",
            "You are an AI researcher conducting hyperparameter tuning for baseline "
            "experiments. Based on the current implementation and previous tuning "
            "attempts, propose and implement ONE new hyperparameter tuning idea to "
            "see if it improves performance. First check whether simply training "
            "longer improves performance, then try common hyperparameters, and only "
            "then method-specific ones.",
        ),
        ("Brief", brief),
        ("Base code you are working on", _code(parent.code)),
        ("Previous tuning attempts", _tried(tried)),
        (
            "Requirements",
            "- Tune ONE specific hyperparameter, different from previous attempts.\n"
            "- The plan should be 3-5 sentences on what is tuned and why.\n"
            "- Submit the complete code, including the parts that didn't change.",
        ),
    )
    return _ask_change(model, prompt, "Hyperparameter")


def ablate(model: str, brief: str, parent: Node, tried: list[str]) -> tuple[str, str]:
    """
    Remove or change one component of a working node, to measure its contribution.

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
            "You are an AI researcher conducting ablation studies. Based on the "
            "current implementation and previous ablations, propose and implement "
            "ONE new ablation study that tests a different aspect of the method.",
        ),
        ("Brief", brief),
        ("Base code you are working on", _code(parent.code)),
        ("Previous ablations", _tried(tried)),
        (
            "Requirements",
            "- Ablate ONE specific component or feature.\n"
            "- It must be a new idea, not a variation of previous ablations.\n"
            "- If only one dataset has been used so far, one of the ablations should "
            "use several (at least 3) different datasets.\n"
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
