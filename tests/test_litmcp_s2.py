"""Tests for litmcp/s2.py, run without network using httpx.MockTransport."""

import httpx
import pytest
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
