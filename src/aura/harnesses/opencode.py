import json

from aura.constants import MCP_CONFIG


def _open_code_config(model: str) -> dict:
    """
    Build OpenCode config: LiteLLM as the Anthropic API, MCP servers from mcp.json.

    Args:
        model: Model name as configured in the LiteLLM gateway.

    Returns:
        OpenCode config as a dictionary.
    """
    servers = json.loads(MCP_CONFIG.read_text())["mcpServers"]
    return {
        "provider": {
            "anthropic": {
                "options": {
                    "baseURL": "http://lite-llm:4000/v1",
                    "apiKey": "{env:ANTHROPIC_API_KEY}",
                }
            }
        },
        "small_model": f"anthropic/{model}",
        "mcp": {
            name: {"type": "remote", "url": s["url"]} for name, s in servers.items()
        },
        "autoupdate": False,
        "share": "disabled",
        "permission": {"question": "deny"},
    }


def opencode_command(prompt: str, model: str) -> list[str]:
    """
    Build a headless OpenCode command connected to the servers in `mcp.json`.

    The command skips permission prompts, as the container is the sandbox, and
    streams one JSON event per agent step.

    Args:
        prompt: Full task prompt.
        model: Model name as configured in the LiteLLM gateway.

    Returns:
        The command to run inside the agent container.
    """
    return [
        "env",
        f"OPENCODE_CONFIG_CONTENT={json.dumps(_open_code_config(model))}",
        "opencode",
        "run",
        prompt,
        "--model",
        f"anthropic/{model}",
        "--format",
        "json",
        "--auto",
    ]
