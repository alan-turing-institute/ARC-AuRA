"""
This module contains the server implementation for the LITMCP framework. It provides the
necessary functionality to handle incoming requests, manage connections, and facilitate
communication between clients and the server. The server is designed to be scalable and
efficient, ensuring that it can handle multiple concurrent connections while maintaining
low latency and high throughput.
"""

import asyncio

import cache
import pdfs
import s2
from mcp.server.mcpserver import Image, MCPServer

mcp = MCPServer("literature")

MAX_PAGES_PER_READ = 10
MAX_CHARS_PER_READ = 40_000  # keeps one read_pages result well inside model context


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
    return await cache.get_or_fetch(
        "search_papers", args, lambda: s2.search_papers(**args)
    )


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
    return await cache.get_or_fetch("get_paper", args, lambda: s2.get_paper(**args))


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
    return await cache.get_or_fetch(
        "get_citations", args, lambda: s2.get_citations(**args)
    )


async def _paper_texts(paper_id: str) -> tuple[dict, list[str]]:
    """Look up a paper, fetch its (cached) PDF and return the paper and its page texts.

    Text is re-extracted from the cached PDF on each call rather than cached itself:
    it is derived deterministically from the PDF, so freezing the PDF freezes it too.
    """
    paper = await get_paper(paper_id.strip())
    path = await pdfs.fetch_pdf(paper)
    # Parsing a PDF is CPU work; a thread keeps the server responsive meanwhile
    texts = await asyncio.to_thread(pdfs.read_texts, path)
    return paper, texts


@mcp.tool()
async def get_fulltext_info(paper_id: str) -> dict:
    """
    Get an overview of a paper's full text: its page count and where each figure and
    table is. Call this first before reading a paper, then use read_pages for the text
    of the pages you need and get_page_image to look at figures or tables.

    Only works for papers with an open-access PDF (most arXiv papers have one). If it
    fails, use get_paper for the abstract instead.

    Args:
        paper_id: Semantic Scholar id, or "DOI:<doi>", or "ARXIV:<arxiv id>".

    Returns:
        The paper's Semantic Scholar paper_id and title, page_count, and figures: a
        list of figure and table captions with the 1-based page each one is on.
    """
    paper, texts = await _paper_texts(paper_id)
    return {
        "paper_id": paper["paper_id"],
        "title": paper.get("title"),
        "page_count": len(texts),
        "figures": pdfs.find_captions(texts),
    }


@mcp.tool()
async def read_pages(paper_id: str, start: int, end: int) -> str:
    """
    Read the text of pages start to end (inclusive) of a paper's PDF. Pages are
    numbered from 1, matching get_fulltext_info. At most 10 pages (or about 40,000
    characters) are returned per call; if the range is cut short, the result ends
    with a note saying where to continue. A single page longer than that limit is
    cut short too, with a note: view the rest of it with get_page_image.

    Args:
        paper_id: Semantic Scholar id, or "DOI:<doi>", or "ARXIV:<arxiv id>".
        start: First page to read (1-based).
        end: Last page to read (1-based, inclusive). Use the same as start for one page.

    Returns:
        The text of each page, each preceded by a "--- page N ---" line.
    """
    _, texts = await _paper_texts(paper_id)
    if not 1 <= start <= end <= len(texts):
        raise ValueError(
            f"Invalid page range {start}-{end}: pages must satisfy "
            f"1 <= start <= end <= {len(texts)} (this paper has {len(texts)} pages)."
        )

    blocks, total, last = [], 0, start - 1
    for page in range(start, min(end, start + MAX_PAGES_PER_READ - 1) + 1):
        text = "\n".join(texts[page - 1].splitlines())  # drop pdfium's "\r"
        block = f"--- page {page} ---\n{text}"
        if total + len(block) > MAX_CHARS_PER_READ:
            if blocks:  # stop before this page; the note below says to resume here
                break
            # This one page alone is over the limit (an unusually large text layer):
            # return the part that fits and say so, rather than an unbounded response
            blocks.append(block[:MAX_CHARS_PER_READ])
            shown = max(MAX_CHARS_PER_READ - (len(block) - len(text)), 0)
            blocks.append(
                f"[Page {page} truncated: showing the first {shown:,} of "
                f"{len(text):,} characters. The rest of this page isn't available "
                f"as text; use get_page_image(paper_id, page={page}) to view it.]"
            )
            last = page
            break
        blocks.append(block)
        total += len(block)
        last = page

    if last < end:
        blocks.append(
            f"[Stopped at page {last} to limit length; continue with "
            f"read_pages(paper_id, start={last + 1}, end={end}).]"
        )
    return "\n\n".join(blocks)


@mcp.tool()
async def get_page_image(paper_id: str, page: int) -> Image:
    """
    Look at one page of a paper's PDF as an image, to read figures, plots, tables or
    equations that don't come through as text. Use get_fulltext_info first to find
    which page a figure or table is on. Pages are numbered from 1.

    Each image is fairly large in context, so request only the pages you need.

    Args:
        paper_id: Semantic Scholar id, or "DOI:<doi>", or "ARXIV:<arxiv id>".
        page: The page to view (1-based).

    Returns:
        A PNG image of the whole page.
    """
    paper = await get_paper(paper_id.strip())
    path = await pdfs.fetch_pdf(paper)
    # Rendering is CPU work; a thread keeps the server responsive meanwhile
    png = await asyncio.to_thread(pdfs.render_page, path, page)
    return Image(data=png, format="png")


if __name__ == "__main__":
    mcp.run(transport="streamable-http", host="0.0.0.0", port=8000, stateless_http=True)
