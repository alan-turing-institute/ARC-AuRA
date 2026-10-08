"""
Tooling for fetching, caching, reading (incl. text, images, and end-to-end) PDFs of
academic literature accessible by agents.
"""

import asyncio
import hashlib
import io
import ipaddress
import json
import logging
import math
import re
import socket
import time
from pathlib import Path

import cache
import httpx
import pypdfium2 as pdfium

logger = logging.getLogger(__name__)

PDF_DIR = cache.CACHE_DIR / "pdfs"
MAX_BYTES = 50 * 1024 * 1024  # 50 MB
MAX_REDIRECTS = 5
ARXIV_GAP = 3.0  # seconds between requests to arxiv.org (arXiv's published policy)
# A caption starts a line with a label, a number and ":" or "." ("Figure 1: ...").
# The separator is what tells it apart from body text like "Table 2 summarizes ..."
CAPTION = re.compile(r"^\s*(Figure|Fig\.|Table)\s*(S?\d+)\s*[:.]\s*(.*)", re.IGNORECASE)
MAX_CAPTION_CHARS = 150  # captions are a map of the paper, not its full text
PAGE_IMAGE_WIDTH = 1200  # pixels: plot labels stay legible without a huge image
# Hard limits on rendered images, whatever page size an (untrusted) PDF declares.
# A4/Letter at 1200 px wide is ~1700 px tall, so ordinary pages are unaffected.
MAX_PAGE_IMAGE_HEIGHT = 4000  # pixels
MAX_PAGE_IMAGE_PIXELS = PAGE_IMAGE_WIDTH * MAX_PAGE_IMAGE_HEIGHT  # ~19 MB as RGBA
MIN_PAGE_IMAGE_SIDE = 16  # pixels: anything thinner is unreadable anyway

# A separate client from s2.py, so the S2 API key is never sent to PDF hosts.
# Redirects are followed by hand in _read_body, so every hop can be checked by
# _check_url before any request is sent.
_headers = {
    "User-Agent": "ARC-AuRA-litmcp/0.1 (research agent sandbox; "
    "https://github.com/alan-turing-institute/ARC-AuRA)"
}
client = httpx.AsyncClient(follow_redirects=False, timeout=60, headers=_headers)
_arxiv_lock = asyncio.Lock()
_last_arxiv = 0.0
_downloading = cache.KeyedLock()  # one download at a time per paper


class UnsafeURLError(Exception):
    """A PDF URL points somewhere litmcp must not send requests to."""


async def _resolve(host: str, port: int) -> list[str]:
    """Return every IP address host resolves to. Replaced in tests."""
    infos = await asyncio.get_running_loop().getaddrinfo(
        host, port, type=socket.SOCK_STREAM
    )
    return [info[4][0] for info in infos]


async def _check_url(url: httpx.URL) -> None:
    """
    Refuse URLs that could reach anything other than the public internet.

    PDF URLs come from Semantic Scholar data and publishers' redirects, so they are
    untrusted. litmcp sits on the sandbox network, so without this check a URL (or a
    redirect) could make it send requests to litellm, the proxy, itself, or other
    private or cloud-metadata addresses (server-side request forgery).

    Hosts with no dot (Docker service names like "litellm", or "localhost") are
    refused outright, and every address the host resolves to must be public.

    Known limitation: the address is resolved again when the request is sent, so a
    DNS server that answers differently the second time ("DNS rebinding") could still
    redirect it. Closing that fully would mean connecting to the checked address.

    Raises:
        UnsafeURLError: The URL is not http(s), or resolves to a non-public address.
    """
    if url.scheme not in ("http", "https"):
        raise UnsafeURLError(f"scheme {url.scheme!r} not allowed: {url}")
    host = url.host
    try:
        ipaddress.ip_address(host)
        is_ip_literal = True
    except ValueError:
        is_ip_literal = False
    if not host or (not is_ip_literal and "." not in host):
        raise UnsafeURLError(f"internal host name not allowed: {url}")

    try:
        addresses = await _resolve(
            host, url.port or (443 if url.scheme == "https" else 80)
        )
    except OSError as e:
        raise UnsafeURLError(f"could not resolve {host}: {e}") from e
    for address in addresses:
        ip = ipaddress.ip_address(address.split("%")[0])  # drop IPv6 zone ids
        if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
            ip = ip.ipv4_mapped  # judge ::ffff:10.0.0.1 as 10.0.0.1
        # is_global is False for private, loopback, link-local (incl. cloud
        # metadata at 169.254.169.254), carrier-grade NAT, reserved and similar
        if not ip.is_global:
            raise UnsafeURLError(f"{host} resolves to non-public address {ip}: {url}")


def _candidate_urls(paper: dict) -> list[str]:
    """Open-access PDF first, then arxiv"""
    urls = []
    if url := paper.get("open_access_pdf"):
        urls.append(url)
    if arxiv := (paper.get("external_ids") or {}).get("ArXiv"):
        urls.append(f"https://arxiv.org/pdf/{arxiv}")
    return urls


async def _read_body(url: str) -> bytes | None:
    """GET url and return its body, or None on a non-2xx status or over MAX_BYTES.

    Redirects are followed here, up to MAX_REDIRECTS, checking each new URL with
    _check_url before requesting it. The body is streamed in chunks, so an oversized
    download is abandoned as soon as it passes MAX_BYTES.

    Raises:
        UnsafeURLError: The URL or a redirect points at a non-public address.
    """
    current = httpx.URL(url)
    for _ in range(MAX_REDIRECTS + 1):
        await _check_url(current)
        async with client.stream("GET", current) as response:
            if response.is_redirect:
                if not (location := response.headers.get("location")):
                    return None
                current = current.join(location)  # handles relative redirects
                continue
            if not response.is_success:
                return None
            chunks, total = [], 0
            async for chunk in response.aiter_bytes():
                total += len(chunk)
                if total > MAX_BYTES:
                    return None
                chunks.append(chunk)
            return b"".join(chunks)
    return None  # too many redirects


async def _download(url: str) -> bytes | None:
    """Download url; return the bytes if it's a real PDF under MAX_BYTES, else None."""
    global _last_arxiv
    try:
        if httpx.URL(url).host == "arxiv.org":
            async with _arxiv_lock:
                wait = ARXIV_GAP - (time.monotonic() - _last_arxiv)
                if wait > 0:
                    await asyncio.sleep(wait)
                try:
                    data = await _read_body(url)
                finally:  # failed requests still count towards arXiv's gap
                    _last_arxiv = time.monotonic()
        else:
            data = await _read_body(url)
    except httpx.HTTPError:  # timeout, dropped connection, malformed URL, etc.
        return None
    except UnsafeURLError as e:
        logger.warning("Refused PDF URL: %s", e)
        return None

    # Every PDF starts with "%PDF"; this catches HTML login pages served as "PDFs".
    # The Content-Type header isn't checked because servers often get it wrong.
    if data is None or not data.startswith(b"%PDF"):
        return None
    return data


async def fetch_pdf(paper: dict) -> Path:
    """
    Return the path to a paper's PDF, downloading and caching it on first use.

    The PDF file itself is the cache: it is stored as `<paper_id>.pdf` using Semantic
    Scholar's id, so a paper referred to by DOI, arXiv id or S2 id shares one file. A
    `.json` sidecar records where it came from and a hash of its contents. Failed
    downloads are not cached, so they are retried next time.

    Concurrent calls for the same paper download it only once: the others wait and
    then use that copy, so every agent reads exactly the same bytes.

    Args:
        paper: The paper as returned by `get_paper`, with `paper_id`,
            `open_access_pdf` and `external_ids`.

    Returns:
        Path to the cached PDF.

    Raises:
        ValueError: No open-access PDF could be found or downloaded.
    """
    path = PDF_DIR / f"{paper['paper_id']}.pdf"
    if path.exists():  # fast path: no lock needed for a hit
        return path

    async with _downloading.hold(paper["paper_id"]):
        if path.exists():  # someone else may have just downloaded it
            return path
        for url in _candidate_urls(paper):
            if (data := await _download(url)) is not None:
                sidecar = {
                    "paper_id": paper["paper_id"],
                    "source_url": url,
                    "sha256": hashlib.sha256(data).hexdigest(),
                    "fetched_at": cache.now(),
                }
                # Sidecar first: the PDF's existence marks a cache hit, so any
                # cached PDF is guaranteed to have its sidecar
                cache.write_atomic(
                    path.with_suffix(".json"), json.dumps(sidecar, indent=2).encode()
                )
                cache.write_atomic(path, data)
                return path

    raise ValueError(
        f"No open-access full text for {paper['paper_id']}; "
        "use get_paper for the abstract."
    )


def read_texts(path: Path) -> list[str]:
    """Read the text from a PDF file, returning a list of pages as strings."""
    with pdfium.PdfDocument(path) as pdf:
        texts = []
        for page in pdf:
            textpage = page.get_textpage()
            texts.append(textpage.get_text_range())
    return texts


def find_captions(texts: list[str]) -> list[dict]:
    """
    Find captions for figures and tables in a list of page texts.

    Only the first line of each caption is kept (cut to MAX_CAPTION_CHARS), as a map
    of where figures are; `read_pages` gives the full text. Labels are normalised, so
    "Fig. 3." and "FIGURE 3:" are both type "Figure", number "3". If a caption appears
    more than once (e.g. "Table 2 (continued)"), only its first page is kept.

    Args:
        texts: Text of each page, in order, as returned by `read_texts`.

    Returns:
        Dicts of {"page" (1-based), "type" ("Figure" or "Table"), "number", "caption"}.
    """
    captions, seen = [], set()
    for page, text in enumerate(texts, start=1):
        for line in text.splitlines():  # handles pdfium's "\r\n" line endings
            if not (match := CAPTION.match(line)):
                continue
            kind = "Figure" if match.group(1).lower().startswith("fig") else "Table"
            number = match.group(2).upper()  # "s1" -> "S1"
            if (kind, number) in seen:
                continue
            seen.add((kind, number))
            captions.append(
                {
                    "page": page,
                    "type": kind,
                    "number": number,
                    "caption": match.group(3).strip()[:MAX_CAPTION_CHARS],
                }
            )
    return captions


def _render_scale(page_width: float, page_height: float, width: int) -> float:
    """
    Choose the render scale for a page of the given size in points (1/72 inch).

    Aims for `width` pixels wide, but scales down further if that would break
    MAX_PAGE_IMAGE_HEIGHT or MAX_PAGE_IMAGE_PIXELS. The page size comes from an
    untrusted PDF: fitting a 1 x 14400 point page to 1200 px wide would otherwise
    mean a 17-million-pixel-tall bitmap and exhaust memory during rendering.

    Raises:
        ValueError: The page has no usable size, or is too extreme a shape to render
            legibly within the limits.
    """
    if not (
        math.isfinite(page_width)
        and math.isfinite(page_height)
        and page_width > 0
        and page_height > 0
    ):
        raise ValueError(f"Page has an invalid size ({page_width} x {page_height}).")
    scale = min(
        width / page_width,
        MAX_PAGE_IMAGE_HEIGHT / page_height,
        math.sqrt(MAX_PAGE_IMAGE_PIXELS / (page_width * page_height)),
    )

    def fits(s: float) -> bool:
        # pdfium rounds each side up to whole pixels, so check the rounded-up size
        w, h = math.ceil(page_width * s), math.ceil(page_height * s)
        return (
            w <= width and h <= MAX_PAGE_IMAGE_HEIGHT and w * h <= MAX_PAGE_IMAGE_PIXELS
        )

    while not fits(scale):  # at most a few steps: only rounding can overshoot
        scale *= 0.999

    if min(page_width, page_height) * scale < MIN_PAGE_IMAGE_SIDE:
        raise ValueError(
            f"Page is too extreme a shape to render ({page_width:.0f} x "
            f"{page_height:.0f} points); use read_pages for its text instead."
        )
    return scale


def render_page(path: Path, page: int, width: int = PAGE_IMAGE_WIDTH) -> bytes:
    """
    Render one page of a PDF as a PNG image.

    The whole page is rendered rather than extracting figure images, because plots in
    PDFs are often vector drawings with no embedded image to extract. The image is at
    most `width` pixels wide, MAX_PAGE_IMAGE_HEIGHT tall and MAX_PAGE_IMAGE_PIXELS in
    total, whatever page size the PDF declares (see _render_scale).

    Args:
        path: The PDF file.
        page: Page number, 1-based.
        width: Target width of the image in pixels; height follows the page's aspect
            ratio, within the limits above.

    Returns:
        The PNG file contents.

    Raises:
        ValueError: The page number is outside the document, or the page's size can't
            be rendered within the limits.
    """
    with pdfium.PdfDocument(path) as pdf:
        if not 1 <= page <= len(pdf):
            raise ValueError(
                f"Invalid page {page}: this paper has {len(pdf)} pages, "
                "numbered from 1."
            )
        pdf_page = pdf[page - 1]
        # get_width/get_height account for the page's /Rotate, i.e. the shape rendered
        scale = _render_scale(pdf_page.get_width(), pdf_page.get_height(), width)
        image = pdf_page.render(scale=scale).to_pil()
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()
