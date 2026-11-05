"""Interface with the literature MCP server"""

import asyncio
import json

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

_LITMCP_URL = "http://litmcp:8000/mcp"


async def _call(name: str, arguments: dict) -> list[dict] | dict:
    """Call one of litmcp's tools over MCP, and return its result."""
    async with (
        streamable_http_client(_LITMCP_URL) as (read, write),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        result = await session.call_tool(name, arguments)
    if result.is_error:
        raise RuntimeError(result.content[0].text)
    if result.structured_content is None:
        return json.loads(result.content[0].text)
    # Lists come wrapped as {"result": [...]}; dicts come as they are
    return result.structured_content.get("result", result.structured_content)


def search_papers(query: str, limit: int = 10) -> list[dict]:
    """
    Search for papers through the literature server

    Args:
        query: The search query string.
        limit: The maximum number of results to return.
    Returns:
        Papers with their paper_id, title, authors, year, venue and url.
    """
    return asyncio.run(_call("search_papers", {"query": query, "limit": limit}))


def get_paper(paper_id: str) -> dict:
    """
    Get a paper's metadata and abstract through the literature server.

    Args:
        paper_id: The paper's ID, from `search_papers`.

    Returns:
        The paper's paper_id, title, authors, year, venue, url and abstract.
    """
    return asyncio.run(_call("get_paper", {"paper_id": paper_id}))
