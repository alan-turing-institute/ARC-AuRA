from inspect_ai.agent import Agent
from inspect_swe import claude_code

from aura.harnesses.mcp import mcp_servers


def claude_code_agent(model: str) -> Agent:
    """
    Build a Claude Code agent using the image's install and the servers in `mcp.json`.

    Web tools are disallowed, as WebSearch runs at the model provider, outside the
    sandbox.

    Args:
        model: Unused; Claude Code's model calls go to the eval's model via the bridge.

    Returns:
        The agent, to use as an Inspect solver.
    """
    return claude_code(
        version="sandbox",
        cwd="/workspace",
        mcp_servers=mcp_servers(),
        disallowed_tools=["WebSearch", "WebFetch"],
    )
