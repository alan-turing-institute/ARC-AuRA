def ai_scientist_v2_command(prompt: str, model: str, stages: list[str]) -> list[str]:
    """
    Build the command that runs the AI Scientist-v2 loop, mounted at `/loops`.

    Args:
        prompt: Full task prompt.
        model: Model name as configured in the LiteLLM gateway.
        stages: Names from `STAGES` to produce outputs for.

    Returns:
        The command to run inside the agent container.
    """
    # The prompt goes first, as `--stages` takes all the arguments after it
    return [
        "env", "PYTHONPATH=/loops", "python", "-m", "ai_scientist_v2", prompt,
        "--model", model, "--stages", *stages,
    ]  # fmt: skip
