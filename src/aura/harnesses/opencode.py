import json

from inspect_ai.agent import Agent
from inspect_swe import opencode

from aura.harnesses.mcp import mcp_servers


def opencode_agent(model: str) -> Agent:
    """
    Build an OpenCode agent using the image's install and the servers in `mcp.json`.

    The model is declared in OpenCode's config, as the image stops OpenCode fetching
    its model list and its built-in list may not include it. Its `question` tool is
    denied, as there is no one to answer it.

    Args:
        model: Model name as configured in the LiteLLM gateway.

    Returns:
        The agent, to use as an Inspect solver.
    """
    config = {
        "autoupdate": False,
        "share": "disabled",
        "permission": {"question": "deny"},
        "provider": {"anthropic": {"models": {model: {}}}},
    }
    return opencode(
        version="sandbox",
        cwd="/workspace",
        opencode_model=f"anthropic/{model}",
        mcp_servers=mcp_servers(),
        env={"OPENCODE_CONFIG_CONTENT": json.dumps(config)},
    )
