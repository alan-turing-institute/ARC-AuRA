"""Tests for litmcp/pdfs.py fetching, run without network using httpx.MockTransport.

`fetch_pdf` takes the paper dict returned by `get_paper` (s2's trimmed format), so no
Semantic Scholar calls are involved here.
"""

import asyncio
import hashlib
import json

import httpx
import pdfs
import pytest
import pytest_asyncio
from conftest import _make_pdf

# A real (tiny) PDF: downloads are now opened with pdfium before being cached
PDF = _make_pdf([["A real PDF."]])
OA_URL = "https://publisher.example/paper.pdf"
ARXIV_URL = "https://arxiv.org/pdf/1706.03762"

# Fake DNS for tests: hosts listed here resolve to these addresses; any other host
# resolves to a public address (a documentation-range IP would count as non-global)
DNS = {
    "internal.example": ["10.0.0.5"],
}
PUBLIC_IP = "93.184.215.14"


def make_paper(open_access_pdf: str | None = OA_URL, arxiv: str | None = "1706.03762"):
    return {
        "paper_id": "204e3073870fae3d05bcbc2f6a8e263d9b72e776",
        "title": "Attention Is All You Need",
        "open_access_pdf": open_access_pdf,
        "external_ids": {"ArXiv": arxiv} if arxiv else {},
    }


@pytest.fixture
def pdf_dir(tmp_path, monkeypatch):
    """Point the PDF cache at a temporary folder, remove arXiv waits, and fake DNS."""

    async def fake_resolve(host: str, port: int) -> list[str]:
        try:  # an IP literal "resolves" to itself, as with real getaddrinfo
            pdfs.ipaddress.ip_address(host)
            return [host]
        except ValueError:
            return DNS.get(host, [PUBLIC_IP])

    monkeypatch.setattr(pdfs, "PDF_DIR", tmp_path / "pdfs")
    monkeypatch.setattr(pdfs, "ARXIV_GAP", 0)
    monkeypatch.setattr(pdfs, "_resolve", fake_resolve)
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
async def test_no_full_text_raises_and_caches_nothing(pdf_dir, serve):
    serve({OA_URL: httpx.Response(403), ARXIV_URL: httpx.Response(503)})

    with pytest.raises(ValueError, match="No open-access full text"):
        await pdfs.fetch_pdf(make_paper())

    assert not pdf_dir.exists() or not any(pdf_dir.iterdir())


# --- SSRF protection: litmcp must only fetch from the public internet ------------


def redirect_to(location: str) -> httpx.Response:
    return httpx.Response(302, headers={"location": location})


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url",
    [
        "http://litellm:4000/health",  # Docker service name on sandbox_net
        "http://169.254.169.254/latest/meta-data/",  # cloud metadata (link-local)
        "https://internal.example/paper.pdf",  # public-looking name, private address
        "file:///etc/passwd",  # non-http schemes
    ],
)
async def test_unsafe_open_access_url_is_never_requested(pdf_dir, serve, url):
    requests = serve({})

    with pytest.raises(ValueError, match="No open-access full text"):
        await pdfs.fetch_pdf(make_paper(open_access_pdf=url, arxiv=None))

    assert requests == []


@pytest.mark.asyncio
async def test_redirect_to_unsafe_destination_is_not_followed(pdf_dir, serve):
    requests = serve({OA_URL: redirect_to("http://litellm:4000/key/info")})

    with pytest.raises(ValueError, match="No open-access full text"):
        await pdfs.fetch_pdf(make_paper(arxiv=None))

    assert [str(r.url) for r in requests] == [OA_URL]  # only the first, safe hop


@pytest.mark.asyncio
async def test_safe_redirects_are_followed(pdf_dir, serve):
    serve(
        {
            OA_URL: redirect_to("/moved/paper.pdf"),  # relative redirect
            "https://publisher.example/moved/paper.pdf": redirect_to(
                "https://cdn.example/paper.pdf"
            ),
            "https://cdn.example/paper.pdf": pdf_response(),
        }
    )

    path = await pdfs.fetch_pdf(make_paper(arxiv=None))

    assert path.read_bytes() == PDF


@pytest.mark.asyncio
async def test_concurrent_fetches_of_one_paper_download_once(
    pdf_dir, serve, monkeypatch
):
    requests = serve({OA_URL: pdf_response()})
    resolve = pdfs._resolve  # the fake DNS from pdf_dir

    async def slow_resolve(host, port):
        # Yield like a real DNS lookup, so concurrent downloads genuinely overlap
        for _ in range(20):
            await asyncio.sleep(0)
        return await resolve(host, port)

    monkeypatch.setattr(pdfs, "_resolve", slow_resolve)

    paths = await asyncio.gather(*(pdfs.fetch_pdf(make_paper()) for _ in range(4)))

    assert len(set(paths)) == 1
    assert len(requests) == 1


# --- Downloads must be complete, readable PDFs before they are cached --------------


def pdf_bytes_response(content: bytes) -> httpx.Response:
    return httpx.Response(
        200, content=content, headers={"content-type": "application/pdf"}
    )


@pytest.mark.asyncio
async def test_unreadable_pdf_is_not_cached_and_arxiv_is_tried(pdf_dir, serve):
    bad = PDF[: int(len(PDF) * 0.9)]  # cut short: pdfium would still open this
    requests = serve({OA_URL: pdf_bytes_response(bad), ARXIV_URL: pdf_response()})

    path = await pdfs.fetch_pdf(make_paper())

    assert path.read_bytes() == PDF  # the good arXiv copy, not the publisher's
    assert [r.url.host for r in requests] == ["publisher.example", "arxiv.org"]
    sidecar = json.loads(path.with_suffix(".json").read_text())
    assert sidecar["source_url"] == ARXIV_URL
