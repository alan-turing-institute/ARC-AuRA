"""Create, block and read the spend of per-run keys on the LiteLLM gateway."""

import os

import httpx

GATEWAY_URL = os.environ.get("LITELLM_URL", "http://localhost:4000")
client = httpx.Client(base_url=GATEWAY_URL, timeout=30)


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
        The run key ("sk-..."), to pass to the agent as RUN_KEY.
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
