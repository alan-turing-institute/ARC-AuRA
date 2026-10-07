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
    """Search for papers. This will first search through the cache to see if the paper
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
    args = {" ".join(query.split()), max(1, min(limit, 50)), year, venue}
    key = cache.key_for("search_papers", *args)
    if (hit := cache.get(key)) is not None:
        return hit
    results = await s2.search_papers(**args)
    cache.put(key, "search_papers", args, results)
    return results


if __name__ == "__main__":
    mcp.run(transport="streamable-http", host="0.0.0.0", port=8000, stateless_http=True)
