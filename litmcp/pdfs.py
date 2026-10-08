"""
Tooling for fetching, caching, reading (incl. text, images, and end-to-end) PDFs of
academic literature accessible by agents.
"""

import asyncio
import hashlib
import io
import json
import re
import time
from pathlib import Path

import cache
import httpx
import pypdfium2 as pdfium

PDF_DIR = cache.CACHE_DIR / "pdfs"
MAX_BYTES = 50 * 1024 * 1024  # 50 MB
ARXIV_GAP = 3.0  # seconds between requests to arxiv.org (arXiv's published policy)
# A caption starts a line with a label, a number and ":" or "." ("Figure 1: ...").
# The separator is what tells it apart from body text like "Table 2 summarizes ..."
CAPTION = re.compile(r"^\s*(Figure|Fig\.|Table)\s*(S?\d+)\s*[:.]\s*(.*)", re.IGNORECASE)
MAX_CAPTION_CHARS = 150  # captions are a map of the paper, not its full text
PAGE_IMAGE_WIDTH = 1200  # pixels: plot labels stay legible without a huge image

# A separate client from s2.py, so the S2 API key is never sent to PDF hosts
_headers = {
    "User-Agent": "ARC-AuRA-litmcp/0.1 (research agent sandbox; "
    "https://github.com/alan-turing-institute/ARC-AuRA)"
}
client = httpx.AsyncClient(follow_redirects=True, timeout=60, headers=_headers)
_arxiv_lock = asyncio.Lock()
_last_arxiv = 0.0


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

    The body is streamed in chunks, so an oversized download is abandoned as soon as
    it passes MAX_BYTES instead of being loaded into memory first.
    """
    async with client.stream("GET", url) as response:
        if not response.is_success:
            return None
        chunks, total = [], 0
        async for chunk in response.aiter_bytes():
            total += len(chunk)
            if total > MAX_BYTES:
                return None
            chunks.append(chunk)
    return b"".join(chunks)


async def _download(url: str) -> bytes | None:
    """Download url; return the bytes if it's a real PDF under MAX_BYTES, else None."""
    global _last_arxiv
    try:
        if "arxiv.org" in url:
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
    except httpx.HTTPError:  # timeout, dropped connection, too many redirects, etc.
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

    Args:
        paper: The paper as returned by `get_paper`, with `paper_id`,
            `open_access_pdf` and `external_ids`.

    Returns:
        Path to the cached PDF.

    Raises:
        ValueError: No open-access PDF could be found or downloaded.
    """
    path = PDF_DIR / f"{paper['paper_id']}.pdf"
    if path.exists():
        return path

    for url in _candidate_urls(paper):
        if (data := await _download(url)) is not None:
            sidecar = {
                "paper_id": paper["paper_id"],
                "source_url": url,
                "sha256": hashlib.sha256(data).hexdigest(),
                "fetched_at": cache.now(),
            }
            # Sidecar first: the PDF's existence marks a cache hit, so any cached
            # PDF is guaranteed to have its sidecar
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


def render_page(path: Path, page: int, width: int = PAGE_IMAGE_WIDTH) -> bytes:
    """
    Render one page of a PDF as a PNG image.

    The whole page is rendered rather than extracting figure images, because plots in
    PDFs are often vector drawings with no embedded image to extract.

    Args:
        path: The PDF file.
        page: Page number, 1-based.
        width: Width of the image in pixels; height follows the page's aspect ratio.

    Returns:
        The PNG file contents.

    Raises:
        ValueError: The page number is outside the document.
    """
    with pdfium.PdfDocument(path) as pdf:
        if not 1 <= page <= len(pdf):
            raise ValueError(
                f"Invalid page {page}: this paper has {len(pdf)} pages, "
                "numbered from 1."
            )
        pdf_page = pdf[page - 1]
        scale = width / pdf_page.get_width()  # PDF widths are in points (1/72 inch)
        image = pdf_page.render(scale=scale).to_pil()
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()
