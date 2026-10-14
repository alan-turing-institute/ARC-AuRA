"""Tests for the full-text tools in litmcp/server.py.

`get_paper` and `pdfs.fetch_pdf` are replaced with fakes, so no network or cache is
involved: the tools read a small PDF built by the `make_pdf` fixture.
"""

import asyncio
import base64

import pytest
import server

PAPER = {
    "paper_id": "204e3073870fae3d05bcbc2f6a8e263d9b72e776",
    "title": "Attention Is All You Need",
}


@pytest.fixture
def paper_pdf(tmp_path, monkeypatch, make_pdf):
    """Serve a fake paper whose pages are given as lists of lines.

    Returns a function: paper_pdf([["page 1 line", ...], ...]) installs that PDF.
    """

    def install(pages: list[list[str]]) -> None:
        path = tmp_path / "paper.pdf"
        path.write_bytes(make_pdf(pages))

        async def fake_get_paper(paper_id):
            return PAPER

        async def fake_fetch_pdf(paper):
            return path

        monkeypatch.setattr(server, "get_paper", fake_get_paper)
        monkeypatch.setattr(server.pdfs, "fetch_pdf", fake_fetch_pdf)

    return install


def numbered_pages(n: int) -> list[list[str]]:
    return [[f"Text of page {i}."] for i in range(1, n + 1)]


# --- get_fulltext_info --------------------------------------------------------


@pytest.mark.asyncio
async def test_fulltext_info_gives_map_of_paper(paper_pdf):
    paper_pdf([["Introduction"], ["Body"], ["Figure 1: Model architecture."]])

    info = await server.get_fulltext_info("ARXIV:1706.03762")

    assert info == {
        "paper_id": PAPER["paper_id"],  # S2's id, not what the agent typed
        "title": "Attention Is All You Need",
        "page_count": 3,
        "figures": [
            {
                "page": 3,
                "type": "Figure",
                "number": "1",
                "caption": "Model architecture.",
            }
        ],
    }


# --- read_pages ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_page_range_is_inclusive(paper_pdf):
    paper_pdf(numbered_pages(5))

    text = await server.read_pages("x", 2, 4)

    for page in (2, 3, 4):
        assert f"--- page {page} ---" in text
    assert "--- page 5 ---" not in text
    assert "Stopped" not in text


@pytest.mark.asyncio
async def test_long_range_is_capped_with_continuation_note(paper_pdf):
    paper_pdf(numbered_pages(15))

    text = await server.read_pages("x", 1, 15)

    assert "--- page 10 ---" in text
    assert "--- page 11 ---" not in text
    assert "continue with read_pages(paper_id, start=11, end=15)" in text


NOTE_ALLOWANCE = 300  # room for the truncation and continuation notes


@pytest.mark.asyncio
async def test_oversized_single_page_is_truncated_with_note(paper_pdf, monkeypatch):
    monkeypatch.setattr(server, "MAX_CHARS_PER_READ", 40)
    paper_pdf([[f"Line {i} of an enormous text layer." for i in range(50)]])

    text = await server.read_pages("x", 1, 1)

    assert len(text) <= 40 + NOTE_ALLOWANCE
    assert text.startswith("--- page 1 ---\nLine 0")
    assert "Line 49" not in text
    assert "Page 1 truncated" in text
    assert "get_page_image(paper_id, page=1)" in text


@pytest.mark.asyncio
async def test_invalid_range_says_how_many_pages(paper_pdf):
    paper_pdf(numbered_pages(3))

    with pytest.raises(ValueError, match="this paper has 3 pages"):
        await server.read_pages("x", 1, 4)


# --- get_page_image -----------------------------------------------------------


@pytest.mark.asyncio
async def test_page_image_reaches_client_as_image_content(paper_pdf):
    paper_pdf(numbered_pages(2))

    # Call through the MCP layer, as a client would, to check the content block type
    result = await server.mcp.call_tool("get_page_image", {"paper_id": "x", "page": 2})

    (block,) = result.content
    assert block.type == "image"
    assert block.mime_type == "image/png"
    assert base64.b64decode(block.data).startswith(b"\x89PNG")


# --- Concurrent agents asking the same question get the same answer ---------------


@pytest.mark.asyncio
async def test_concurrent_identical_searches_share_one_live_result(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(server.cache, "CACHE_DIR", tmp_path)
    calls = []

    async def live_search(**args):
        calls.append(args)
        for _ in range(20):  # yield, as a real request would
            await asyncio.sleep(0)
        authors = [f"Author {i}" for i in range(7)]
        return [{"paper_id": f"result-of-call-{len(calls)}", "authors": authors}]

    monkeypatch.setattr(server.s2, "search_papers", live_search)

    results = await asyncio.gather(
        server.search_papers("transformers"),
        server.search_papers("  transformers  "),  # normalises to the same query
        server.search_papers("transformers", limit=10),  # default made explicit
    )

    assert len(calls) == 1
    assert results[0] == results[1] == results[2]
    (paper,) = results[0]
    assert len(paper["authors"]) == 5  # the default max_authors
    assert paper["author_count"] == 7
