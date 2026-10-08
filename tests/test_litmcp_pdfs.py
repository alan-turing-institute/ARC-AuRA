"""Tests for litmcp/pdfs.py fetching, run without network using httpx.MockTransport.

`fetch_pdf` takes the paper dict returned by `get_paper` (s2's trimmed format), so no
Semantic Scholar calls are involved here.
"""

import hashlib
import json

import httpx
import pdfs
import pytest
import pytest_asyncio

PDF = b"%PDF-1.4 fake pdf body"
OA_URL = "https://publisher.example/paper.pdf"
ARXIV_URL = "https://arxiv.org/pdf/1706.03762"


def make_paper(open_access_pdf: str | None = OA_URL, arxiv: str | None = "1706.03762"):
    return {
        "paper_id": "204e3073870fae3d05bcbc2f6a8e263d9b72e776",
        "title": "Attention Is All You Need",
        "open_access_pdf": open_access_pdf,
        "external_ids": {"ArXiv": arxiv} if arxiv else {},
    }


@pytest.fixture
def pdf_dir(tmp_path, monkeypatch):
    """Point the PDF cache at a temporary folder and remove arXiv waits."""
    monkeypatch.setattr(pdfs, "PDF_DIR", tmp_path / "pdfs")
    monkeypatch.setattr(pdfs, "ARXIV_GAP", 0)
    return tmp_path / "pdfs"


@pytest_asyncio.fixture
async def serve(monkeypatch):
    """Replace pdfs.client with one answering from `routes` ({url: Response}).

    Returns the list of requests made, so tests can check what was fetched.
    """
    requests: list[httpx.Request] = []
    clients: list[httpx.AsyncClient] = []

    def install(routes: dict[str, httpx.Response]) -> list[httpx.Request]:
        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            for url, response in routes.items():
                if str(request.url).startswith(url):
                    return response
            return httpx.Response(404)

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        clients.append(client)
        monkeypatch.setattr(pdfs, "client", client)
        return requests

    yield install
    for client in clients:
        await client.aclose()


def pdf_response() -> httpx.Response:
    return httpx.Response(200, content=PDF, headers={"content-type": "application/pdf"})


@pytest.mark.asyncio
async def test_open_access_url_is_downloaded_and_cached(pdf_dir, serve):
    requests = serve({OA_URL: pdf_response()})

    path = await pdfs.fetch_pdf(make_paper())

    assert path == pdf_dir / "204e3073870fae3d05bcbc2f6a8e263d9b72e776.pdf"
    assert path.read_bytes() == PDF
    assert [str(r.url) for r in requests] == [OA_URL]  # arXiv not needed
    assert "x-api-key" not in requests[0].headers  # S2 key never sent to publishers

    sidecar = json.loads(path.with_suffix(".json").read_text())
    assert sidecar["paper_id"] == "204e3073870fae3d05bcbc2f6a8e263d9b72e776"
    assert sidecar["source_url"] == OA_URL
    assert sidecar["sha256"] == hashlib.sha256(PDF).hexdigest()
    assert "fetched_at" in sidecar


@pytest.mark.asyncio
async def test_falls_back_to_arxiv_without_open_access_url(pdf_dir, serve):
    requests = serve({ARXIV_URL: pdf_response()})

    path = await pdfs.fetch_pdf(make_paper(open_access_pdf=None))

    assert path.read_bytes() == PDF
    assert len(requests) == 1
    assert requests[0].url.host == "arxiv.org"
    assert "1706.03762" in requests[0].url.path


@pytest.mark.asyncio
async def test_html_pretending_to_be_pdf_is_rejected(pdf_dir, serve):
    # Publisher returns a 200 HTML page, even claiming to be a PDF; arXiv has the real one
    html = httpx.Response(
        200,
        content=b"<html>Please log in</html>",
        headers={"content-type": "application/pdf"},
    )
    serve({OA_URL: html, ARXIV_URL: pdf_response()})

    path = await pdfs.fetch_pdf(make_paper())

    assert path.read_bytes() == PDF
    sidecar = json.loads(path.with_suffix(".json").read_text())
    assert sidecar["source_url"].startswith("https://arxiv.org/")


@pytest.mark.asyncio
async def test_pdf_with_unusual_content_type_is_accepted(pdf_dir, serve):
    # Servers often mislabel PDFs; the bytes, not the header, decide
    mislabelled = httpx.Response(
        200, content=PDF, headers={"content-type": "application/octet-stream"}
    )
    serve({OA_URL: mislabelled})

    path = await pdfs.fetch_pdf(make_paper(arxiv=None))

    assert path.read_bytes() == PDF


@pytest.mark.asyncio
async def test_no_full_text_raises_and_caches_nothing(pdf_dir, serve):
    serve({OA_URL: httpx.Response(403), ARXIV_URL: httpx.Response(503)})

    with pytest.raises(ValueError, match="No open-access full text"):
        await pdfs.fetch_pdf(make_paper())

    assert not pdf_dir.exists() or not any(pdf_dir.iterdir())


@pytest.mark.asyncio
async def test_paper_without_any_pdf_link_raises_without_requests(pdf_dir, serve):
    requests = serve({})

    with pytest.raises(ValueError, match="No open-access full text"):
        await pdfs.fetch_pdf(make_paper(open_access_pdf=None, arxiv=None))

    assert requests == []


@pytest.mark.asyncio
async def test_network_error_falls_through_to_next_url(pdf_dir, monkeypatch, serve):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "arxiv.org":
            return pdf_response()
        raise httpx.ConnectTimeout("publisher timed out")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        monkeypatch.setattr(pdfs, "client", client)
        path = await pdfs.fetch_pdf(make_paper())

    assert path.read_bytes() == PDF


@pytest.mark.asyncio
async def test_second_call_is_served_from_cache(pdf_dir, serve):
    requests = serve({OA_URL: pdf_response()})

    first = await pdfs.fetch_pdf(make_paper())
    second = await pdfs.fetch_pdf(make_paper())

    assert first == second
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_oversized_download_is_rejected(pdf_dir, monkeypatch, serve):
    monkeypatch.setattr(pdfs, "MAX_BYTES", 10)
    serve({OA_URL: pdf_response()})  # PDF is longer than 10 bytes

    with pytest.raises(ValueError, match="No open-access full text"):
        await pdfs.fetch_pdf(make_paper(arxiv=None))

    assert not pdf_dir.exists() or not any(pdf_dir.iterdir())
