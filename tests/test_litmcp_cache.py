"""Tests for litmcp/cache.py: keys, storage, and single-flight fetching."""

import asyncio
import json

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


# --- keys and storage -------------------------------------------------------------


def test_key_ignores_argument_order():
    assert cache.key_for("t", {"a": 1, "b": None}) == cache.key_for(
        "t", {"b": None, "a": 1}
    )


def test_key_depends_on_tool_and_arguments():
    keys = {
        cache.key_for("search_papers", {"query": "x"}),
        cache.key_for("search_papers", {"query": "y"}),
        cache.key_for("get_paper", {"query": "x"}),
    }
    assert len(keys) == 3


def test_put_then_get_round_trips_including_empty_results(cache_dir):
    key = cache.key_for("t", {"q": "x"})
    assert cache.get(key) is None

    cache.put(key, "t", {"q": "x"}, [])

    assert cache.get(key) == []
    entry = json.loads((cache_dir / f"{key}.json").read_text())
    assert entry["tool"] == "t"
    assert entry["args"] == {"q": "x"}
    assert "fetched_at" in entry


def test_write_atomic_leaves_no_temp_files(cache_dir):
    cache.write_atomic(cache_dir / "sub" / "f.bin", b"data")

    assert (cache_dir / "sub" / "f.bin").read_bytes() == b"data"
    assert [p.name for p in (cache_dir / "sub").iterdir()] == ["f.bin"]


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
async def test_different_keys_are_fetched_concurrently():
    in_flight, most_in_flight = 0, 0

    async def fetch():
        nonlocal in_flight, most_in_flight
        in_flight += 1
        most_in_flight = max(most_in_flight, in_flight)
        await let_others_run()
        in_flight -= 1
        return []

    await asyncio.gather(
        *(cache.get_or_fetch("t", {"query": q}, fetch) for q in ("a", "b", "c"))
    )

    assert most_in_flight == 3  # no lock shared between different questions


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


@pytest.mark.asyncio
async def test_cache_hit_does_not_fetch():
    cache.put(cache.key_for("t", {"q": "x"}), "t", {"q": "x"}, ["stored"])

    async def fetch():
        raise AssertionError("should not fetch on a hit")

    assert await cache.get_or_fetch("t", {"q": "x"}, fetch) == ["stored"]


# --- KeyedLock housekeeping ---------------------------------------------------------


@pytest.mark.asyncio
async def test_keyed_lock_forgets_keys_when_released():
    locks = cache.KeyedLock()

    async def use(key):
        async with locks.hold(key):
            await let_others_run()

    await asyncio.gather(use("a"), use("a"), use("b"))

    assert len(locks) == 0  # no memory kept for keys no one is using


@pytest.mark.asyncio
async def test_keyed_lock_released_when_body_raises():
    locks = cache.KeyedLock()

    with pytest.raises(ValueError, match="boom"):
        async with locks.hold("a"):
            raise ValueError("boom")

    assert len(locks) == 0
    async with locks.hold("a"):  # and can be taken again
        pass
