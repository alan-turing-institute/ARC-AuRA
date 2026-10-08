"""
Thin client for the Semantic Scholar Graph API, with rate limiting and retries.
See https://www.semanticscholar.org/product/api. Caching is handled by the caller.
"""

import asyncio
import os
import time

import httpx

BASE_URL = "https://api.semanticscholar.org/graph/v1"
FIELDS = "title,authors,year,venue,citationCount,externalIds,url"

_headers = {"x-api-key": key} if (key := os.environ.get("S2_API_KEY")) else {}
client = httpx.AsyncClient(base_url=BASE_URL, headers=_headers, timeout=30)

_lock = asyncio.Lock()
_last_call = 0.0
# time.monotonic() before which no request may be sent by anyone: set when S2 rate
# limits us, because the limit applies to the shared API key, not to one request
_not_before = 0.0
MIN_GAP = 1.0  # seconds between requests (S2 allows ~1 request/second with a key)
MAX_ATTEMPTS = 4
MAX_RETRY_AFTER = (
    60.0  # seconds: cap on an honoured Retry-After, so a bogus one can't stall us
)


def _error_message(response: httpx.Response) -> str:
    """Pull S2's own error message out of a failed response, for the model to read."""
    try:
        body = response.json()
    except ValueError:
        return response.text or f"HTTP {response.status_code}"
    return body.get("error") or body.get("message") or f"HTTP {response.status_code}"


def _retry_delay(response: httpx.Response | None, attempt: int) -> float:
    """Seconds to wait before retrying: S2's Retry-After if given (capped at
    MAX_RETRY_AFTER), else 1, 2, 4..."""
    if response is not None:
        try:
            return min(
                max(float(response.headers["Retry-After"]), 0.0), MAX_RETRY_AFTER
            )
        except (KeyError, ValueError):
            pass
    return 2.0**attempt


def _pauses_everyone(response: httpx.Response | None) -> bool:
    """Whether a failed response means the whole API key should back off.

    A 429 is a rate limit on our key, and a Retry-After header (e.g. on a 503) is the
    server asking all clients to wait. Other server errors and network failures only
    back off the request that hit them.
    """
    return response is not None and (
        response.status_code == 429 or "Retry-After" in response.headers
    )


async def _get(path: str, params: dict) -> dict:
    """
    Make a GET request to the Semantic Scholar API, with rate limiting and retries.

    Requests from all callers are queued so only one is sent at a time, at least
    MIN_GAP seconds apart. Rate limiting (429), server errors (5xx) and network failures
    are retried, up to MAX_ATTEMPTS in total. A 429 (or any Retry-After) pauses *all*
    callers until the server's requested time, since they share one API key; other
    failures back off only the request that hit them (exponentially: 1, 2, 4 s).

    Args:
        path: API path relative to BASE_URL, e.g. "/paper/search".
        params: Query parameters.

    Returns:
        The parsed JSON response.

    Raises:
        ValueError: The request was invalid or the paper doesn't exist (4xx). The
            message is S2's own, so the model can correct its arguments.
        RuntimeError: S2 was still unavailable after MAX_ATTEMPTS.
    """
    global _last_call, _not_before
    response = None
    for attempt in range(MAX_ATTEMPTS):
        # The lock covers the throttle, the request and recording any server-wide
        # pause, so the next caller in the queue always sees the pause before sending.
        # A request's own backoff (below) happens outside it, so it holds no one up.
        async with _lock:
            now = time.monotonic()
            wait = max(MIN_GAP - (now - _last_call), _not_before - now)
            if wait > 0:
                await asyncio.sleep(wait)
            try:
                response = await client.get(path, params=params)
            except httpx.TransportError:  # timeout, dropped connection, etc.
                response = None
            _last_call = time.monotonic()
            if _pauses_everyone(response):
                pause_until = _last_call + _retry_delay(response, attempt)
                _not_before = max(_not_before, pause_until)

        if response is not None:
            if response.status_code == 429 or response.status_code >= 500:
                pass  # retry below
            elif response.status_code >= 400:
                raise ValueError(_error_message(response))
            else:
                response.raise_for_status()
                return response.json()

        # A server-wide pause is waited out under the lock on the next attempt;
        # anything else backs off just this request
        if attempt < MAX_ATTEMPTS - 1 and not _pauses_everyone(response):
            await asyncio.sleep(_retry_delay(response, attempt))

    reason = "network error" if response is None else _error_message(response)
    raise RuntimeError(
        f"Semantic Scholar unavailable after {MAX_ATTEMPTS} attempts ({reason}). "
        "Try again later."
    )


def _trim(raw: dict, with_abstract: bool = False) -> dict:
    """
    Reformat the semantic scholar output to fit our schema.
    """
    paper = {
        "paper_id": raw.get("paperId"),
        "title": raw.get("title"),
        "authors": [a.get("name") for a in (raw.get("authors") or [])[:5]],
        "year": raw.get("year"),
        "venue": raw.get("venue"),
        "citation_count": raw.get("citationCount"),
        "external_ids": {
            k: v
            for k, v in (raw.get("externalIds") or {}).items()
            if k in ("DOI", "ArXiv")
        },
        "url": raw.get("url"),
    }
    if with_abstract:
        paper["abstract"] = raw.get("abstract")
        paper["open_access_pdf"] = (raw.get("openAccessPdf") or {}).get("url")
    return paper


async def search_papers(
    query: str, limit: int = 10, year: str | None = None, venue: str | None = None
) -> list[dict]:
    """
    Search for papers using the Semantic Scholar API.
    """
    params = {
        "query": query,
        "limit": limit,
        "year": year,
        "venue": venue,
        "fields": FIELDS,
    }
    params = {k: v for k, v in params.items() if v is not None}
    data = await _get("/paper/search", params)
    return [_trim(paper) for paper in data.get("data") or []]


async def get_paper(paper_id: str) -> dict:
    """
    Get a paper by its paper_id using the Semantic Scholar API.
    """
    params = {"fields": FIELDS + ",abstract,openAccessPdf"}
    data = await _get(f"/paper/{paper_id}", params)
    return _trim(data, with_abstract=True)


async def get_citations(paper_id: str, limit: int = 20) -> list[dict]:
    """
    Get the citations for a paper by its paper_id using the Semantic Scholar API.
    """
    params = {"limit": limit, "fields": FIELDS}
    data = await _get(f"/paper/{paper_id}/citations", params)
    citing = [citation.get("citingPaper") for citation in data.get("data") or []]
    return [_trim(paper) for paper in citing if paper]
