"""Tests for litmcp/pdfs.py fetching, run without network using httpx.MockTransport.

`fetch_pdf` takes the paper dict returned by `get_paper` (s2's trimmed format), so no
Semantic Scholar calls are involved here.
"""

import asyncio
import hashlib
import json
import threading
import time

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
    "metadata.example": ["169.254.169.254"],
    "mixed.example": ["93.184.215.14", "192.168.1.1"],
    "mapped.example": ["::ffff:10.0.0.5"],
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


# --- SSRF protection: litmcp must only fetch from the public internet ------------


def redirect_to(location: str) -> httpx.Response:
    return httpx.Response(302, headers={"location": location})


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url",
    [
        "http://litellm:4000/health",  # Docker service name on sandbox_net
        "http://proxy:3128/",
        "http://localhost:8000/mcp",
        "http://127.0.0.1:8000/mcp",  # litmcp itself
        "http://10.1.2.3/paper.pdf",  # private ranges
        "http://172.18.0.2/paper.pdf",
        "http://192.168.1.1/paper.pdf",
        "http://169.254.169.254/latest/meta-data/",  # cloud metadata (link-local)
        "http://100.64.0.1/paper.pdf",  # carrier-grade NAT
        "http://[::1]:8000/mcp",  # IPv6 loopback
        "http://[fd00::1]/paper.pdf",  # IPv6 private
        "https://internal.example/paper.pdf",  # public-looking name, private address
        "https://metadata.example/paper.pdf",
        "https://mixed.example/paper.pdf",  # any non-public address is enough
        "https://mapped.example/paper.pdf",  # IPv4-mapped IPv6 of a private address
        "file:///etc/passwd",  # non-http schemes
        "ftp://publisher.example/paper.pdf",
    ],
)
async def test_unsafe_open_access_url_is_never_requested(pdf_dir, serve, url):
    requests = serve({})

    with pytest.raises(ValueError, match="No open-access full text"):
        await pdfs.fetch_pdf(make_paper(open_access_pdf=url, arxiv=None))

    assert requests == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "location",
    [
        "http://litellm:4000/key/info",
        "http://169.254.169.254/latest/meta-data/",
        "https://internal.example/paper.pdf",
        "file:///etc/passwd",
    ],
)
async def test_redirect_to_unsafe_destination_is_not_followed(pdf_dir, serve, location):
    requests = serve({OA_URL: redirect_to(location)})

    with pytest.raises(ValueError, match="No open-access full text"):
        await pdfs.fetch_pdf(make_paper(arxiv=None))

    assert [str(r.url) for r in requests] == [OA_URL]  # only the first, safe hop


@pytest.mark.asyncio
async def test_unsafe_url_falls_back_to_arxiv(pdf_dir, serve):
    requests = serve({ARXIV_URL: pdf_response()})

    path = await pdfs.fetch_pdf(make_paper(open_access_pdf="http://litellm:4000/"))

    assert path.read_bytes() == PDF
    assert [r.url.host for r in requests] == ["arxiv.org"]


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
async def test_redirect_loop_gives_up(pdf_dir, serve, monkeypatch):
    monkeypatch.setattr(pdfs, "MAX_REDIRECTS", 3)
    requests = serve({OA_URL: redirect_to(OA_URL)})

    with pytest.raises(ValueError, match="No open-access full text"):
        await pdfs.fetch_pdf(make_paper(arxiv=None))

    assert len(requests) == 4  # the first request plus 3 redirects


@pytest.mark.asyncio
async def test_unresolvable_host_is_refused(pdf_dir, serve, monkeypatch):
    async def failing_resolve(host, port):
        raise OSError("Name or service not known")

    monkeypatch.setattr(pdfs, "_resolve", failing_resolve)
    requests = serve({})

    with pytest.raises(ValueError, match="No open-access full text"):
        await pdfs.fetch_pdf(make_paper(arxiv=None))

    assert requests == []


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
@pytest.mark.parametrize(
    "bad",
    [
        PDF[: int(len(PDF) * 0.9)],  # cut short: pdfium would still open this
        PDF[: len(PDF) // 2],  # cut short: pdfium refuses this
        b"%PDF-1.4\n"
        + b"\x00garbage" * 50
        + b"\n%%EOF\n",  # right markers, corrupt body
        _make_pdf([]),  # well-formed but no pages
    ],
    ids=["truncated-90pc", "truncated-50pc", "corrupt", "no-pages"],
)
async def test_unreadable_pdf_is_not_cached_and_arxiv_is_tried(pdf_dir, serve, bad):
    requests = serve({OA_URL: pdf_bytes_response(bad), ARXIV_URL: pdf_response()})

    path = await pdfs.fetch_pdf(make_paper())

    assert path.read_bytes() == PDF  # the good arXiv copy, not the publisher's
    assert [r.url.host for r in requests] == ["publisher.example", "arxiv.org"]
    sidecar = json.loads(path.with_suffix(".json").read_text())
    assert sidecar["source_url"] == ARXIV_URL


@pytest.mark.asyncio
async def test_unreadable_pdf_with_no_alternative_caches_nothing(pdf_dir, serve):
    serve({OA_URL: pdf_bytes_response(PDF[: len(PDF) // 2])})

    with pytest.raises(ValueError, match="No open-access full text"):
        await pdfs.fetch_pdf(make_paper(arxiv=None))

    assert not pdf_dir.exists() or not any(pdf_dir.iterdir())


def test_trailing_bytes_after_eof_marker_are_accepted():
    # Some generators append whitespace or junk after %%EOF; real readers accept it
    assert pdfs._is_complete_pdf(PDF + b"\n" * 10 + b"junk")


def test_pdfium_is_never_used_by_two_threads_at_once(tmp_path, monkeypatch):
    path = tmp_path / "paper.pdf"
    path.write_bytes(_make_pdf([["Page one"], ["Page two"]]))
    active, most_active = 0, 0
    counter = threading.Lock()
    real_document = pdfs.pdfium.PdfDocument

    class TrackedDocument(real_document):
        def __init__(self, *args, **kwargs):
            nonlocal active, most_active
            with counter:
                active += 1
                most_active = max(most_active, active)
            time.sleep(0.01)  # widen the window for overlap
            super().__init__(*args, **kwargs)

        def close(self):
            nonlocal active
            with counter:
                active -= 1
            super().close()

    monkeypatch.setattr(pdfs.pdfium, "PdfDocument", TrackedDocument)

    async def hammer():
        jobs = []
        for _ in range(4):
            jobs.append(asyncio.to_thread(pdfs.read_texts, path))
            jobs.append(asyncio.to_thread(pdfs.render_page, path, 1, 200))
            jobs.append(asyncio.to_thread(pdfs._is_complete_pdf, path.read_bytes()))
        return await asyncio.gather(*jobs)

    results = asyncio.run(hammer())

    assert most_active == 1
    assert all(results)
