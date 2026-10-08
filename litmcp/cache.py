"""
On-disk cache of tool results, so every agent asking the same question gets the same
answer. Each entry is one JSON file named by a hash of the tool name and its arguments.
"""

import asyncio
import contextlib
import hashlib
import json
import os
import tempfile
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# /cache in the container (set via env var); ./litmcp/cache when run locally
CACHE_DIR = Path(os.environ.get("LITMCP_CACHE_DIR", Path(__file__).parent / "cache"))


def key_for(tool: str, args: dict[str, Any]) -> str:
    """
    Build a deterministic cache key from a tool name and its arguments.

    The same tool and arguments always give the same key, regardless of the order the
    arguments were given in.

    Args:
        tool: Name of the tool, e.g. "search_papers".
        args: The tool's normalised arguments, by name.

    Returns:
        A hex SHA-256 digest, safe to use as a filename.
    """
    canonical = json.dumps({"tool": tool, "args": args}, sort_keys=True)
    return hashlib.sha256(canonical.encode()).hexdigest()


def get(key: str) -> Any | None:
    """
    Look up a cached result.

    Args:
        key: Key from `key_for`.

    Returns:
        The stored result, or None if there is no entry for this key.
    """
    path = CACHE_DIR / f"{key}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text())["result"]


def put(key: str, tool: str, args: dict[str, Any], result: Any) -> None:
    """
    Store a result in the cache.

    The request is stored alongside the result so cache files can be inspected by hand.

    Args:
        key: Key from `key_for`.
        tool: Name of the tool.
        args: The arguments the key was built from.
        result: The JSON-serialisable result to store.
    """
    entry = {
        "tool": tool,
        "args": args,
        "fetched_at": now(),
        "result": result,
    }
    write_atomic(CACHE_DIR / f"{key}.json", json.dumps(entry, indent=2).encode())


def write_atomic(path: Path, data: bytes) -> None:
    """
    Write bytes to a file so that readers never see it half-written.

    The data goes to a temporary file in the same folder, which is then renamed over
    the target in one step. Concurrent agents therefore see either no file or the
    complete one.

    Args:
        path: Destination file. Its folder is created if needed.
        data: The bytes to write.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
    except BaseException:
        os.unlink(tmp)
        raise


def now() -> str:
    """Current UTC time as an ISO 8601 string, for `fetched_at` fields."""
    return datetime.now(timezone.utc).isoformat()


class KeyedLock:
    """
    One asyncio lock per key, created on demand and dropped when no one holds or waits
    for it, so memory doesn't grow with the number of distinct keys ever seen.

    Callers using the same key run one at a time; different keys don't block each
    other. This is only safe within one process (the server runs as one), which is
    also why no locking is needed around the bookkeeping below: asyncio code can't be
    interrupted between awaits.
    """

    def __init__(self) -> None:
        self._locks: dict[str, asyncio.Lock] = {}
        self._users: dict[str, int] = {}

    @contextlib.asynccontextmanager
    async def hold(self, key: str) -> AsyncIterator[None]:
        lock = self._locks.setdefault(key, asyncio.Lock())
        self._users[key] = self._users.get(key, 0) + 1
        try:
            async with lock:
                yield
        finally:
            self._users[key] -= 1
            if not self._users[key]:
                del self._users[key], self._locks[key]

    def __len__(self) -> int:
        """Number of keys currently held or waited for."""
        return len(self._locks)


_fetching = KeyedLock()


async def get_or_fetch(
    tool: str, args: dict[str, Any], fetch: Callable[[], Awaitable[Any]]
) -> Any:
    """
    Return the cached result for a tool call, or fetch, store and return it.

    Concurrent calls with the same tool and arguments are "single-flighted": only the
    first calls `fetch`, and the others wait and then read what it stored. Without this,
    two agents asking the same question at the same moment could both miss the cache
    and each get a different live answer, breaking the guarantee that everyone sees
    the same results. Errors from `fetch` are not cached, so a later call retries.

    Args:
        tool: Name of the tool, e.g. "search_papers".
        args: The tool's normalised arguments, by name.
        fetch: Called with no arguments to get the live result on a cache miss.

    Returns:
        The cached or freshly fetched result.
    """
    key = key_for(tool, args)
    if (hit := get(key)) is not None:  # fast path: no lock needed for a hit
        return hit
    async with _fetching.hold(key):
        # Check again: whoever held the lock before us may have just stored it
        if (hit := get(key)) is not None:
            return hit
        result = await fetch()
        put(key, tool, args, result)
        return result
