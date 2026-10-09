from aura.constants import MCP_CONFIG


def claude_code_command(prompt: str, model: str) -> list[str]:
    """Build a headless Claude Code command connected to the servers in `mcp.json`."""
    return [
        "claude", "-p", prompt, "--model", model,
        "--mcp-config", MCP_CONFIG.read_text(), "--strict-mcp-config",
        "--output-format", "json", "--dangerously-skip-permissions",
    ]  # fmt: skip
