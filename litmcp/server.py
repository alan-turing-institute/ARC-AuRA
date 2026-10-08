"""
This module contains the server implementation for the LITMCP framework. It provides the
necessary functionality to handle incoming requests, manage connections, and facilitate
communication between clients and the server. The server is designed to be scalable and
efficient, ensuring that it can handle multiple concurrent connections while maintaining
low latency and high throughput.
"""

import cache
import s2
from mcp.server.mcpserver import MCPServer

mcp = MCPServer("literature")


# Echo tool for testing the server's responsiveness
@mcp.tool()
async def echo(text: str) -> str:
    """Echo the input text back to the client.

    Args:
        text: The text to be echoed back.

    Returns:
        The same text that was received as input.
    """
    return text


@mcp.tool()
async def search_papers(
    query: str,
    limit: int = 10,
    year: str | None = None,
    venue: str | None = None,
) -> list[dict]:
    """
    Search for papers. This will first search through the cache to see if the paper
    has already been found, and then using Semantic Scholar, with the following
    possible search options:

        NB: Author's name will have to be provided in the query string, as Semantic
            Scholar does not provide a separate author search parameter.

    Args:
        query: Search query for the paper.
        limit: Total number of papers to be returned, this is clamped 1-50.
            Defaults to 10.
        year: Year range over which to search for papers, with S2's syntax being the
            following:
            ("2019", "2016-2020", "2018-").
            Defaults to None.
        venue: Venue name if known. Defaults to None.

    Returns:
        List of dictionaries containing the search results, with each dictionary
        representing a paper, containing a paper_id that can be passed to get_paper or
        get_citations.
    """
    # Construct arguments for the search functions
    args = {
        "query": " ".join(query.split()),
        "limit": max(1, min(limit, 50)),
        "year": year,
        "venue": venue,
    }
    key = cache.key_for("search_papers", args)
    if (hit := cache.get(key)) is not None:
        return hit
    results = await s2.search_papers(**args)
    cache.put(key, "search_papers", args, results)
    return results


@mcp.tool()
async def get_paper(paper_id: str) -> dict:
    """
    Get a paper by its paper_id. This will first search through the cache to see if the
    paper has already been found, and then using Semantic Scholar.

    Args:
        paper_id: The unique identifier for the paper.
    Returns:
        Metadata for the paper, with a dictionary containing the paper's details.
    """
    args = {"paper_id": paper_id.strip()}
    key = cache.key_for("get_paper", args)
    if (hit := cache.get(key)) is not None:
        return hit
    result = await s2.get_paper(**args)
    cache.put(key, "get_paper", args, result)
    return result


@mcp.tool()
async def get_citations(paper_id: str, limit: int = 20) -> list[dict]:
    """
    Get the citations for a paper by its paper_id. This will first search through the
    cache to see if the citations have already been found, and then using Semantic
    Scholar.

    Args:
        paper_id: The unique identifier for the paper.
        limit: Maximum number of citing papers to return, clamped to 1-100.
    Returns:
        List of dictionaries containing the citations for the paper, with each dictionary
        representing a citation.
    """
    args = {"paper_id": paper_id.strip(), "limit": max(1, min(limit, 100))}
    key = cache.key_for("get_citations", args)
    if (hit := cache.get(key)) is not None:
        return hit
    result = await s2.get_citations(**args)
    cache.put(key, "get_citations", args, result)
    return result


if __name__ == "__main__":
    mcp.run(transport="streamable-http", host="0.0.0.0", port=8000, stateless_http=True)
