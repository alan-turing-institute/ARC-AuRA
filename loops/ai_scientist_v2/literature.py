"""Interface with the literature MCP server"""

import asyncio
import json

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

LITMCP_URL = "http://localhost:8000/mcp"


async def _search(query: str, limit: int = 10) -> list[dict]:
    """
    Wraps an async MCP session to search for papers using the literature MCP server.

    Args:
        query: The search query string.
        limit: The maximum number of results to return.
    Returns:
        List of dictionaries containing the search results, with each dictionary
        representing a paper, containing a paper_id that can be passed to get_paper or
        get_citations. author_count gives each paper's total number of authors.
    """
    async with streamable_http_client(LITMCP_URL) as (read, write):
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
        Papers with their paper_id, titl, authors, year and abstract.
    """
    return asyncio.run(_search(query, limit))
