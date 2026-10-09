"""Tests for litmcp/s2.py, run without network using httpx.MockTransport."""

import asyncio
import heapq
import itertools
from types import SimpleNamespace
from urllib.parse import unquote

import httpx
import pytest
import pytest_asyncio
import s2


@pytest.mark.asyncio
async def test_search_trims_results(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/graph/v1/paper/search"
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "paperId": "123",
                        "title": "Test Paper",
                        "authors": [{"name": "Author A"}],
                        "year": 2021,
                        "venue": "Test Venue",
                        "citationCount": 5,
                        "externalIds": {"DOI": "10.1234/test"},
                        "url": "https://example.com",
                    }
                ]
            },
        )

    async with httpx.AsyncClient(
        base_url=s2.BASE_URL, transport=httpx.MockTransport(handler)
    ) as fake:
        monkeypatch.setattr(s2, "client", fake)
        monkeypatch.setattr(s2, "MIN_GAP", 0)  # avoid waiting in tests
        papers = await s2.search_papers("test query")
    assert papers[0]["paper_id"] == "123"


# --- Rate limiting and retries, on a virtual clock ------------------------------


class VirtualClock:
    """Fake time for s2: sleeps return instantly but advance `now` in wake order.

    `run` drives several coroutines at once: it lets every task run until all are
    blocked, then wakes the earliest sleeper, so concurrent timing is exact.
    """

    def __init__(self) -> None:
        self.now = 1000.0
        self._sleepers: list[tuple[float, int, asyncio.Future]] = []
        self._order = itertools.count()

    def monotonic(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        if seconds <= 0:
            await asyncio.sleep(0)
            return
        wake = asyncio.get_running_loop().create_future()
        heapq.heappush(self._sleepers, (self.now + seconds, next(self._order), wake))
        await wake

    async def run(self, *coros):
        tasks = [asyncio.create_task(c) for c in coros]
        while not all(t.done() for t in tasks):
            for _ in range(50):  # let runnable tasks progress until they block
                await asyncio.sleep(0)
            if self._sleepers:
                when, _, wake = heapq.heappop(self._sleepers)
                self.now = max(self.now, when)
                wake.set_result(None)
        return await asyncio.gather(*tasks, return_exceptions=True)


@pytest.fixture
def clock(monkeypatch):
    """Put s2 on a virtual clock with fresh throttling state."""
    clock = VirtualClock()
    monkeypatch.setattr(s2, "time", SimpleNamespace(monotonic=clock.monotonic))
    monkeypatch.setattr(s2, "asyncio", SimpleNamespace(sleep=clock.sleep))
    monkeypatch.setattr(s2, "_lock", asyncio.Lock())
    monkeypatch.setattr(s2, "_last_call", 0.0)
    monkeypatch.setattr(s2, "_not_before", 0.0)
    return clock


@pytest_asyncio.fixture
async def api(monkeypatch, clock):
    """Serve S2 requests with `respond(request, n)`, n = how many came before.

    Returns the list of (time sent, query) for every request, in order.
    """
    sent: list[tuple[float, str]] = []
    clients: list[httpx.AsyncClient] = []

    def install(respond):
        def handler(request: httpx.Request) -> httpx.Response:
            sent.append((clock.now, request.url.params.get("query", "")))
            return respond(request, len(sent) - 1)

        client = httpx.AsyncClient(
            base_url=s2.BASE_URL, transport=httpx.MockTransport(handler)
        )
        clients.append(client)
        monkeypatch.setattr(s2, "client", client)
        return sent

    yield install
    for client in clients:
        await client.aclose()


def ok(request=None, n=0) -> httpx.Response:
    return httpx.Response(200, json={"data": []})


def search(query: str):
    return s2.search_papers(query)


@pytest.mark.asyncio
async def test_rate_limit_pauses_every_caller(clock, api):
    # The first request is rate limited for 5 s; both callers share the API key
    sent = api(
        lambda r, n: (
            httpx.Response(429, headers={"Retry-After": "5"}) if n == 0 else ok()
        )
    )

    results = await clock.run(search("a"), search("b"))

    assert results == [[], []]
    first = sent[0][0]
    assert all(t >= first + 5 for t, _ in sent[1:]), (
        sent
    )  # nobody sent during the pause


@pytest.mark.asyncio
async def test_rate_limit_pause_is_seen_by_already_queued_callers(clock, api):
    # "b" is already waiting for the lock when "a" gets the 429
    sent = api(
        lambda r, n: (
            httpx.Response(429, headers={"Retry-After": "5"})
            if r.url.params["query"] == "a" and n == 0
            else ok()
        )
    )

    await clock.run(search("a"), search("b"), search("c"))

    first = sent[0][0]
    later = [t for t, q in sent[1:]]
    assert min(later) >= first + 5


@pytest.mark.asyncio
async def test_retry_after_is_capped(clock, api):
    sent = api(
        lambda r, n: (
            httpx.Response(429, headers={"Retry-After": "86400"}) if n == 0 else ok()
        )
    )

    await clock.run(search("a"))

    assert sent[1][0] - sent[0][0] == s2.MAX_RETRY_AFTER


@pytest.mark.asyncio
async def test_retry_after_on_server_error_pauses_every_caller(clock, api):
    sent = api(
        lambda r, n: (
            httpx.Response(503, headers={"Retry-After": "3"}) if n == 0 else ok()
        )
    )

    await clock.run(search("a"), search("b"))

    assert all(t >= sent[0][0] + 3 for t, _ in sent[1:])


@pytest.mark.asyncio
async def test_server_error_backs_off_only_that_request(clock, api):
    # "a" hits a plain 500 (no Retry-After); "b" shouldn't wait for a's backoff
    sent = api(
        lambda r, n: (
            httpx.Response(500) if r.url.params["query"] == "a" and n == 0 else ok()
        )
    )

    await clock.run(search("a"), search("b"))

    first = sent[0][0]
    b_sent = next(t for t, q in sent if q == "b")
    assert b_sent - first == s2.MIN_GAP  # just the normal spacing


@pytest.mark.asyncio
async def test_requests_are_spaced_by_min_gap(clock, api):
    sent = api(ok)

    await clock.run(search("a"), search("b"), search("c"))

    times = [t for t, _ in sent]
    assert [b - a for a, b in itertools.pairwise(times)] == [s2.MIN_GAP] * 2


@pytest.mark.asyncio
async def test_persistent_server_errors_give_up_with_backoff(clock, api):
    sent = api(lambda r, n: httpx.Response(503, text="down"))

    (result,) = await clock.run(search("a"))

    assert isinstance(result, RuntimeError)
    assert f"after {s2.MAX_ATTEMPTS} attempts" in str(result)
    times = [t for t, _ in sent]
    assert [b - a for a, b in itertools.pairwise(times)] == [1, 2, 4]


@pytest.mark.asyncio
async def test_network_errors_are_retried_then_reported(clock, api):
    def fail(request, n):
        raise httpx.ConnectTimeout("timed out")

    sent = api(fail)

    (result,) = await clock.run(search("a"))

    assert isinstance(result, RuntimeError)
    assert "network error" in str(result)
    assert len(sent) == s2.MAX_ATTEMPTS


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "message"),
    [(404, "Paper with id X not found"), (400, "Unacceptable year")],
)
async def test_client_errors_raise_s2_message_without_retrying(
    clock, api, status, message
):
    sent = api(lambda r, n: httpx.Response(status, json={"error": message}))

    (result,) = await clock.run(search("a"))

    assert isinstance(result, ValueError)
    assert str(result) == message
    assert len(sent) == 1


# --- Paper ids are sent as one encoded path segment ---------------------------------

RESERVED_IDS = [
    "DOI:10.1000/abc#def",  # "#" would start a fragment
    "DOI:10.1000/abc?x=1",  # "?" would start a query
    "DOI:10.1000/50%off",  # "%" would start an escape
    "DOI:10.1002/(SICI)1097-4636(199706)35:3<329::AID-JBM7>3.0.CO;2-K",  # real SICI DOI
    "DOI:10.1000/with space",
    "x/../../author/1",  # would otherwise walk to a different endpoint
]


@pytest.fixture
def capture(monkeypatch):
    """Answer every S2 request with an empty paper, recording the requests."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        body = {"data": []} if request.url.path.endswith("/citations") else {}
        return httpx.Response(200, json=body)

    monkeypatch.setattr(
        s2,
        "client",
        httpx.AsyncClient(base_url=s2.BASE_URL, transport=httpx.MockTransport(handler)),
    )
    monkeypatch.setattr(s2, "MIN_GAP", 0)
    monkeypatch.setattr(s2, "_lock", asyncio.Lock())
    return seen


def sent_id(request: httpx.Request, endpoint: str = "") -> str:
    """The paper id as Semantic Scholar will decode it from the request path."""
    raw = request.url.raw_path.decode().split("?")[0]
    prefix = "/graph/v1/paper/"
    assert raw.startswith(prefix)
    assert raw.endswith(endpoint)
    segment = raw[len(prefix) : len(raw) - len(endpoint)]
    assert "/" not in segment  # one path segment: nothing can escape /paper/
    return unquote(segment)


@pytest.mark.asyncio
@pytest.mark.parametrize("paper_id", RESERVED_IDS)
async def test_get_paper_sends_whole_id_with_reserved_characters(capture, paper_id):
    await s2.get_paper(paper_id)

    (request,) = capture
    assert sent_id(request) == paper_id
    assert set(request.url.params) == {"fields"}  # no query smuggled in via the id
    assert not request.url.fragment


@pytest.mark.asyncio
@pytest.mark.parametrize("paper_id", RESERVED_IDS)
async def test_get_citations_sends_whole_id_with_reserved_characters(capture, paper_id):
    await s2.get_citations(paper_id, limit=5)

    (request,) = capture
    assert sent_id(request, "/citations") == paper_id
    assert set(request.url.params) == {"fields", "limit"}
