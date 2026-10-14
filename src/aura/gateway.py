"""Connection gateway for Aura for key separation and cost tracking."""

import os

import httpx

GATEWAY_URL = os.environ.get("LITELLM_URL", "http://localhost:4000")
client = httpx.Client(base_url=GATEWAY_URL, timeout=30)


def _request(method: str, path: str, **kwargs) -> dict:
    """Call a LiteLLM admin endpoint with the master key; return the JSON body."""
    headers = {"Authorization": f"Bearer {os.environ['LITELLM_MASTER_KEY']}"}
    try:
        response = client.request(method, path, headers=headers, **kwargs)
    except httpx.ConnectError:
        raise RuntimeError(
            f"Can't reach LiteLLM at {GATEWAY_URL}; is it running? `docker compose up -d litellm`"
        ) from None
    if not response.is_success:
        try:
            message = response.json()["error"]["message"]
        except (ValueError, KeyError):
            message = response.text
        raise RuntimeError(f"LiteLLM {path} failed ({response.status_code}): {message}")
    return response.json()


def create_run_key(
    run_id: str, model: str, max_budget: float, duration: str, metadata: dict
) -> str:
    """
    Send POST /key/generate with models, budget, duration, metadata to the gateway, and
    allowed routes. Return the run key from the gateway's response.

    Args:
        run_id: Unique ID for this run.
        model: Model name as configured in the LiteLLM gateway.
        max_budget: Maximum spend for this run, in USD.
        duration: Maximum duration for this run.
        metadata: Arbitrary key-value pairs to attach to the run.
    Returns:
        A run key string to use in the `Authorization` header for this run.
    """
    body = _request(
        "POST",
        "/key/generate",
        json={
            "run_id": run_id,
            "model": model,
            "max_budget": max_budget,
            "duration": duration,
            "metadata": metadata,
            "allowed_routes": ["llm_api_routes"],
        },
    )
    return body["key"]


def block_key(key: str) -> None:
    """
    Send POST /key/block to the gateway to block a run key.

    Args:
        key: The run key to block.
    """
    _request("POST", "/key/block", json={"key": key})


def get_spend(key: str) -> float:
    """
    Send GET /key/info?key=... to the gateway to get the spend for a run key.

    Args:
        key: The run key to check.
    Returns:
        The spend for the run key, in USD.
    """
    return _request("GET", "/key/info", params={"key": key})["spend"]
