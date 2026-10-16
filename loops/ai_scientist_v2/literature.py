"""Interface with the literature MCP server"""

import asyncio
import json

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

_LITMCP_URL = "http://litmcp:8000/mcp"


async def _search(query: str, limit: int = 10) -> list[dict]:
    """Call litmcp's search_papers tool over MCP"""
    async with streamable_http_client(_LITMCP_URL) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(
                "search_papers", {"query": query, "limit": limit}
            )
        if result.is_error:
            raise RuntimeError(result.content[0].text)
        if result.structured_content is not None:
            return result.structured_content["result"]
        return json.loads(result.content[0].text)


def search_papers(query: str, limit: int = 10) -> list[dict]:
    """
    Search for papers through the literature server

    Args:
        query: The search query string.
        limit: The maximum number of results to return.
    Returns:
        Papers with their paper_id, title, authors, year and abstract.
    """
    return asyncio.run(_search(query, limit))
