def claude_code_command(prompt: str, model: str) -> list[str]:
    """Build a headless Claude Code command."""
    return [
        "claude", "-p", prompt, "--model", model,
        "--output-format", "json", "--dangerously-skip-permissions",
    ]  # fmt: skip
