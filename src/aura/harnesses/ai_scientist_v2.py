def ai_scientist_v2_command(prompt: str, model: str) -> str:
    """
    Build a headless AI Scientist v2 command connected to the servers in `mcp.json`.

    Args:
        prompt: Full task prompt.
        model: Model name as configured in the LiteLLM gateway.
    Returns:
        The command to run inside the agent container.
    """
    return [
        "env",
        "PYTHONPATH=/loops",
        "python",
        "-m",
        "ai_scientist_v2",
        "--model",
        model,
        prompt,
    ]
