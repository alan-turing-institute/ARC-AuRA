"""
On-disk cache of tool results, so every agent asking the same question gets the same
answer. Each entry is one JSON file named by a hash of the tool name and its arguments.
"""

import hashlib
import json
import os
import tempfile
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
    The file is written to a temporary name and then renamed, so a concurrent reader
    never sees a half-written file.

    Args:
        key: Key from `key_for`.
        tool: Name of the tool.
        args: The arguments the key was built from.
        result: The JSON-serialisable result to store.
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    entry = {
        "tool": tool,
        "args": args,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "result": result,
    }
    fd, tmp = tempfile.mkstemp(dir=CACHE_DIR, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(entry, f, indent=2)
        os.replace(tmp, CACHE_DIR / f"{key}.json")
    except BaseException:
        os.unlink(tmp)
        raise
