"""Tests for litmcp/cache.py: keys, storage, and single-flight fetching."""

import asyncio

import cache
import pytest


@pytest.fixture(autouse=True)
def cache_dir(tmp_path, monkeypatch):
    """Point the cache at a temporary folder for every test."""
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path)
    return tmp_path


async def let_others_run(times: int = 20) -> None:
    """Yield to the event loop, as a real network call would while waiting."""
    for _ in range(times):
        await asyncio.sleep(0)


# --- get_or_fetch: concurrent identical requests fetch once -------------------------


@pytest.mark.asyncio
async def test_concurrent_identical_calls_fetch_once_and_agree():
    calls = []

    async def fetch():
        calls.append(1)
        await let_others_run()  # the window in which a second caller could miss too
        return [f"live result #{len(calls)}"]  # differs per call, like a live search

    results = await asyncio.gather(
        *(cache.get_or_fetch("search_papers", {"query": "x"}, fetch) for _ in range(5))
    )

    assert len(calls) == 1
    assert all(r == ["live result #1"] for r in results)


@pytest.mark.asyncio
async def test_failed_fetch_is_not_cached_and_waiters_retry():
    attempts = []

    async def fetch():
        attempts.append(1)
        await let_others_run()
        if len(attempts) == 1:
            raise RuntimeError("Semantic Scholar unavailable")
        return ["ok"]

    results = await asyncio.gather(
        cache.get_or_fetch("t", {"q": "x"}, fetch),
        cache.get_or_fetch("t", {"q": "x"}, fetch),
        return_exceptions=True,
    )

    assert isinstance(results[0], RuntimeError)  # the first caller sees the error
    assert results[1] == ["ok"]  # the waiter tries again rather than reusing it
    assert len(attempts) == 2


# --- KeyedLock housekeeping ---------------------------------------------------------


@pytest.mark.asyncio
async def test_keyed_lock_forgets_keys_when_released():
    locks = cache.KeyedLock()

    async def use(key):
        async with locks.hold(key):
            await let_others_run()

    await asyncio.gather(use("a"), use("a"), use("b"))

    assert len(locks) == 0  # no memory kept for keys no one is using
