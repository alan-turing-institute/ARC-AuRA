from inspect_ai.agent import Agent
from inspect_swe import claude_code

from aura.harnesses.mcp import mcp_servers


def claude_code_agent(model: str) -> Agent:
    """
    Build a Claude Code agent using the image's install and the servers in `mcp.json`.

    Web tools are disallowed, as WebSearch runs at the model provider, outside the
    sandbox.

    Args:
        model: Model name as configured in the LiteLLM gateway; sets the model
            Claude Code presents as. Its calls go to the eval's model via the bridge.

    Returns:
        The agent, to use as an Inspect solver.
    """
    return claude_code(
        version="sandbox",
        cwd="/workspace",
        model_config=model,
        mcp_servers=mcp_servers(),
        disallowed_tools=["WebSearch", "WebFetch"],
    )
