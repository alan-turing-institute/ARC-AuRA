"""Tests for src/aura/gateway.py, run without network using httpx.MockTransport."""

import contextlib
import json

import httpx
import pytest

from aura import gateway

MASTER_KEY = "sk-master-secret"
RUN_KEY = "sk-run-secret"


@pytest.fixture
def serve(monkeypatch):
    """Answer gateway requests with `handler`; return the list of requests made."""
    monkeypatch.setenv("LITELLM_MASTER_KEY", MASTER_KEY)
    requests: list[httpx.Request] = []

    def install(handler):
        def record(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return handler(request)

        transport = httpx.MockTransport(record)
        client = httpx.Client(base_url=gateway.GATEWAY_URL, transport=transport)
        monkeypatch.setattr(gateway, "client", client)
        return requests

    return install


def test_create_run_key_sends_limits_with_master_key(serve):
    requests = serve(lambda r: httpx.Response(200, json={"key": RUN_KEY}))

    key = gateway.create_run_key("run1", ["m1", "m2"], 2.0, "1h", {"tier": 1})

    assert key == RUN_KEY
    (request,) = requests
    assert request.headers["authorization"] == f"Bearer {MASTER_KEY}"
    assert json.loads(request.content) == {
        "key_alias": "run-run1",
        "models": ["m1", "m2"],
        "max_budget": 2.0,
        "duration": "1h",
        "metadata": {"tier": 1},
        "allowed_routes": ["llm_api_routes"],
    }


def test_get_spend_reads_key_info(serve):
    serve(lambda r: httpx.Response(200, json={"key": "hashed", "info": {"spend": 0.4}}))

    assert gateway.get_spend(RUN_KEY) == 0.4


def test_errors_give_litellm_message_without_keys(serve):
    error = {"error": {"message": "Invalid key"}}
    serve(lambda r: httpx.Response(400, json=error))

    # get_spend sends the run key in the URL, so it's the case most likely to leak
    with pytest.raises(RuntimeError, match="Invalid key") as excinfo:
        gateway.get_spend(RUN_KEY)

    assert RUN_KEY not in str(excinfo.value)
    assert MASTER_KEY not in str(excinfo.value)


@pytest.fixture
def lifecycle(serve, monkeypatch):
    """Answer key create, block and info requests; return the paths requested."""
    monkeypatch.setattr(gateway, "SPEND_WAIT", 0)
    responses = {
        "/key/generate": {"key": RUN_KEY},
        "/key/block": {},
        "/key/info": {"info": {"spend": 0.25}},
    }
    requests = serve(lambda r: httpx.Response(200, json=responses[r.url.path]))
    return lambda: [r.url.path for r in requests]


@pytest.mark.parametrize("fails", [False, True])
def test_run_key_is_blocked_and_cost_recorded(lifecycle, tmp_path, fails):
    with (
        pytest.raises(RuntimeError) if fails else contextlib.nullcontext(),
        gateway.run_key(tmp_path, ["claude-haiku-4-5"], 0.5, "10m", {}) as key,
    ):
        assert key == RUN_KEY
        if fails:
            raise RuntimeError("Run error")

    assert lifecycle() == ["/key/generate", "/key/block", "/key/info"]
    cost = (tmp_path / "cost.json").read_text()
    assert json.loads(cost)["spend_usd"] == 0.25
    assert RUN_KEY not in cost
