"""
Manage per-run keys on the LiteLLM gateway.

`run_key` covers a run's whole key lifecycle: it creates the key, blocks it when
the run ends, and records the run's spend in its run folder.
"""

import json
import os
import sys
import time
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

import httpx

GATEWAY_URL = os.environ.get("LITELLM_URL", "http://localhost:4000")
client = httpx.Client(base_url=GATEWAY_URL, timeout=30)
SPEND_WAIT = 12  # seconds: LiteLLM writes spend to its database every 10 s


def _request(method: str, path: str, **kwargs) -> dict:
    """Call a LiteLLM admin endpoint with the master key; return the JSON body."""
    headers = {"Authorization": f"Bearer {os.environ['LITELLM_MASTER_KEY']}"}
    try:
        response = client.request(method, path, headers=headers, **kwargs)
    except httpx.RequestError as e:
        raise RuntimeError(
            f"Can't reach LiteLLM at {GATEWAY_URL} ({e}); is it running? "
            "`docker compose up -d litellm`"
        ) from None
    if not response.is_success:
        try:
            message = response.json()["error"]["message"]
        except (ValueError, KeyError):
            message = response.text
        raise RuntimeError(f"LiteLLM {path} failed ({response.status_code}): {message}")
    return response.json()


def create_run_key(
    run_id: str, model: str, max_budget: float, max_duration: str, metadata: dict
) -> str:
    """
    Create a key for one run, limited to one model, a budget, an expiry and model calls.

    Args:
        run_id: Unique ID for this run (its run folder name); the key's alias is
            "run-<run_id>".
        model: Model name as configured in the LiteLLM gateway.
        max_budget: Maximum spend for this run, in USD.
        max_duration: How long the key is valid, in LiteLLM's format, e.g. "1h".
        metadata: Details stored with the key, e.g. task, harness and tier.

    Returns:
        The run key ("sk-...").
    """
    body = _request(
        "POST",
        "/key/generate",
        json={
            "key_alias": f"run-{run_id}",
            "models": [model],
            "max_budget": max_budget,
            "duration": max_duration,
            "metadata": metadata,
            "allowed_routes": ["llm_api_routes"],
        },
    )
    return body["key"]


def block_key(key: str) -> None:
    """Block a run key, so it's refused from now on but its spend history is kept."""
    _request("POST", "/key/block", json={"key": key})


def get_spend(key: str) -> float:
    """Return what a run key has spent so far, in USD."""
    return _request("GET", "/key/info", params={"key": key})["info"]["spend"]


def _warn(run_dir: Path, message: str) -> None:
    """Print a warning and append it to the run's `warnings.txt`."""
    line = f"Warning: {message}\n"
    sys.stderr.write(line)
    with (run_dir / "warnings.txt").open("a") as log:
        log.write(line)


def _close_run_key(key: str, run_dir: Path, budget: float, max_duration: str) -> None:
    """
    Block a run's key and write what it spent to `cost.json`.

    Gateway failures only give a warning, so they can't hide an error from the run
    itself; the key's expiry still stops it being used.

    Args:
        key: The run's key, from `create_run_key`.
        run_dir: Run folder to write `cost.json` to.
        budget: The key's budget in USD, recorded alongside the spend.
        max_duration: The key's expiry, recorded alongside the spend.
    """
    try:
        block_key(key)
    except RuntimeError as e:
        _warn(run_dir, f"couldn't block the run's key: {e}")
    try:
        time.sleep(SPEND_WAIT)  # let LiteLLM write the run's last spend
        spend = get_spend(key)
    except RuntimeError as e:
        _warn(run_dir, f"couldn't read the run's spend: {e}")
        return
    cost = {
        "key_alias": f"run-{run_dir.name}",
        "max_budget": budget,
        "duration": max_duration,
        "spend_usd": spend,
    }
    (run_dir / "cost.json").write_text(json.dumps(cost, indent=2))


@contextmanager
def run_key(
    run_dir: Path, model: str, budget: float, max_duration: str, metadata: dict
) -> Generator[str]:
    """
    Create a key for a run, then block it and record its spend when the run ends.

    The key is closed however the run ends, including on error.

    Args:
        run_dir: Run folder; its name is the run ID and `cost.json` is written to it.
        model: Model name as configured in the LiteLLM gateway.
        budget: Maximum spend for the run, in USD.
        max_duration: How long the key is valid, in LiteLLM's format, e.g. "1h".
        metadata: Details stored with the key, e.g. task, harness and tier.

    Yields:
        The run key, for the duration of the `with` block.
    """
    key = create_run_key(run_dir.name, model, budget, max_duration, metadata)
    try:
        yield key
    finally:
        _close_run_key(key, run_dir, budget, max_duration)
