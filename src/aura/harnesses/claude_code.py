from aura.constants import MCP_CONFIG


def claude_code_command(prompt: str, model: str) -> list[str]:
    """
    Build a headless Claude Code command connected to the servers in `mcp.json`.

    The command skips permission prompts, as the container is the sandbox, and
    streams one JSON event per agent step.

    Args:
        prompt: Full task prompt.
        model: Model name as configured in the LiteLLM gateway.

    Returns:
        The command to run inside the agent container.
    """
    return [
        "claude", "-p", prompt, "--model", model,
        "--mcp-config", MCP_CONFIG.read_text(), "--strict-mcp-config",
        "--output-format", "stream-json", "--verbose",
        "--dangerously-skip-permissions",
    ]  # fmt: skip
