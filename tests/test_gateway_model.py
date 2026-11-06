"""Gateway model retry tests using synthetic errors and mock HTTP only."""

import json

import httpx2
import pytest
from anthropic import RateLimitError
from inspect_ai.model import GenerateConfig
from inspect_ai.model._providers.anthropic import AnthropicAPI
from tenacity import wait_none

from aura.sandbox import gateway_model

BUDGET_ERROR = {
    "message": "Budget has been exceeded! Current cost: 0.1, Max budget: 0.1",
    "type": "budget_exceeded",
    "param": None,
    "code": "429",
}


@pytest.fixture(autouse=True)
def no_retry_wait(monkeypatch):
    """Keep real retry decisions but avoid backoff delays in offline tests."""
    monkeypatch.setattr(
        "inspect_ai.model._retry.wait_exponential_jitter",
        lambda **kwargs: wait_none(),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{"error": BUDGET_ERROR}, BUDGET_ERROR])
async def test_gateway_budget_error_stops_generate_retries(monkeypatch, body):
    requests = []

    def respond(request):
        requests.append(request)
        # The SDK has its own finite retries. A different error on the next
        # Inspect attempt bounds this regression even on the original code.
        if len(requests) > 3:
            return httpx2.Response(
                400, json={"error": {"type": "invalid_request_error"}}
            )
        return httpx2.Response(429, json=body, headers={"retry-after-ms": "1"})

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(respond)) as client:
        monkeypatch.setattr(
            AnthropicAPI, "_http_default_args", lambda self: {"http_client": client}
        )
        async with gateway_model("claude-haiku-4-5", "sk-synthetic-run") as model:
            with pytest.raises(RateLimitError) as excinfo:
                await model.generate("Hello", config=GenerateConfig(max_tokens=16))

            error = excinfo.value
            assert error.body == body
            assert excinfo.value.status_code == 429
            assert model.should_retry(error) is False
            assert len(requests) == 3  # only the SDK's default two retries
            assert json.loads(requests[0].content)["model"] == "claude-haiku-4-5"
            assert requests[0].headers["x-api-key"] == "sk-synthetic-run"
            assert str(requests[0].url) == f"{model.api.base_url}/v1/messages"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "body", "retry", "kind"),
    [
        (429, {"error": {"type": "rate_limit_error"}}, True, "rate_limit"),
        (
            429,
            {"error": {"type": "rate_limit_error", "message": "budget_exceeded"}},
            True,
            "rate_limit",
        ),
        (429, {"error": {"code": "budget_exceeded"}}, True, "rate_limit"),
        (429, {"message": "budget_exceeded"}, True, "rate_limit"),
        (429, {"error": {"type": "Budget_Exceeded"}}, True, "rate_limit"),
        (429, {"error": {"type": ["budget_exceeded"]}}, True, "rate_limit"),
        (429, {"error": {"type": {"type": "budget_exceeded"}}}, True, "rate_limit"),
        (429, {"error": None, "type": "budget_exceeded"}, True, "rate_limit"),
        (429, {"error": "budget_exceeded"}, True, "rate_limit"),
        (429, {"error": []}, True, "rate_limit"),
        (429, {}, True, "rate_limit"),
        (429, None, True, "rate_limit"),
        (429, [], True, "rate_limit"),
        (429, 429, True, "rate_limit"),
        (429, '{"error": {"type": "budget_exceeded"}}', True, "rate_limit"),
        (429, "malformed JSON {", True, "rate_limit"),
        (400, {"error": BUDGET_ERROR}, False, "transient"),
        (401, {"error": {"type": "authentication_error"}}, False, "transient"),
        (503, {"error": BUDGET_ERROR}, True, "transient"),
        (529, {"error": {"type": "overloaded_error"}}, True, "transient"),
    ],
)
async def test_other_errors_preserve_parent_decision(
    monkeypatch, status, body, retry, kind
):
    from anthropic import APIStatusError

    parent = AnthropicAPI.should_retry
    decisions = []

    def classify(self, error):
        decision = parent(self, error)
        decisions.append(decision)
        return decision

    monkeypatch.setattr(AnthropicAPI, "should_retry", classify)
    response = httpx2.Response(
        status,
        request=httpx2.Request("POST", "https://gateway.example/v1/messages"),
        headers={"retry-after": "7"},
    )
    error = APIStatusError("synthetic provider error", response=response, body=body)
    async with gateway_model("claude-haiku-4-5", "sk-synthetic-run") as model:
        decision = model.api.should_retry(error)
        assert len(decisions) == 1
        assert decision is decisions[0]
        assert bool(decision) is retry
        assert decision.kind == kind
        assert decision.retry_after == (7 if retry else None)
        assert model.should_retry(error) is retry


@pytest.mark.asyncio
async def test_connection_errors_preserve_parent_decision():
    from anthropic import APIConnectionError, APITimeoutError

    request = httpx2.Request("POST", "https://gateway.example/v1/messages")
    async with gateway_model("claude-haiku-4-5", "sk-synthetic-run") as model:
        for error in (
            APIConnectionError(request=request),
            APITimeoutError(request=request),
            httpx2.ConnectError("synthetic connection failure", request=request),
            ValueError("budget_exceeded"),
        ):
            assert model.api.should_retry(error) == AnthropicAPI.should_retry(
                model.api, error
            )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "body"),
    [
        (429, {"error": {"type": "rate_limit_error"}}),
        (429, {"error": "budget_exceeded"}),
        (503, {"error": {"type": "api_error"}}),
    ],
)
async def test_generate_retries_other_errors_until_success(monkeypatch, status, body):
    requests = []

    def respond(request):
        requests.append(request)
        if len(requests) <= 3:
            return httpx2.Response(status, json=body, headers={"retry-after-ms": "1"})
        return httpx2.Response(
            200,
            json={
                "id": "msg_synthetic",
                "type": "message",
                "role": "assistant",
                "model": "claude-haiku-4-5",
                "content": [{"type": "text", "text": "Hello"}],
                "stop_reason": "end_turn",
                "stop_sequence": None,
                "usage": {"input_tokens": 1, "output_tokens": 1},
            },
        )

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(respond)) as client:
        monkeypatch.setattr(
            AnthropicAPI, "_http_default_args", lambda self: {"http_client": client}
        )
        async with gateway_model("claude-haiku-4-5", "sk-synthetic-run") as model:
            output = await model.generate("Hello", config=GenerateConfig(max_tokens=16))
            assert output.completion == "Hello"
            assert len(requests) == 4  # reaches Inspect's retry after SDK retries


@pytest.mark.asyncio
async def test_agent_and_monitor_use_gateway_policy_and_anthropic_identity(
    monkeypatch, tmp_path
):
    from types import SimpleNamespace

    from inspect_ai.model import get_model

    from aura import sandbox

    captured = {}

    def evaluate(task, **kwargs):
        captured.update(kwargs)
        return [SimpleNamespace(status="success")]

    monkeypatch.setattr(sandbox, "eval", evaluate)
    sandbox.run_in_sandbox(
        object(), tmp_path, "claude-sonnet-4-6", "claude-haiku-4-5", "sk-synthetic-run"
    )
    for model, name in (
        (captured["model"], "claude-sonnet-4-6"),
        (captured["model_roles"]["monitor"], "claude-haiku-4-5"),
    ):
        async with (
            model,
            get_model(
                f"anthropic/{name}",
                base_url=sandbox.GATEWAY_URL,
                api_key="sk-synthetic-run",
            ) as parent,
        ):
            assert isinstance(model.api, AnthropicAPI)
            assert type(model.api) is not AnthropicAPI
            assert type(parent.api) is AnthropicAPI
            assert model.name == parent.name == name
            assert str(model) == str(parent) == f"anthropic/{name}"
            assert model.api.qualified_model_name == parent.api.qualified_model_name
            assert model.canonical_name() == parent.canonical_name()
            assert model.api.base_url == parent.api.base_url == sandbox.GATEWAY_URL
            assert (
                model.explicit_base_url
                == parent.explicit_base_url
                == sandbox.GATEWAY_URL
            )
            assert model.api.api_key == parent.api.api_key == "sk-synthetic-run"
            assert model.config == parent.config
            assert model.api.client.max_retries == parent.api.client.max_retries == 2
            error = RateLimitError(
                "synthetic budget error",
                response=httpx2.Response(
                    429, request=httpx2.Request("POST", sandbox.GATEWAY_URL)
                ),
                body={"error": BUDGET_ERROR},
            )
            assert not model.api.should_retry(error)
            assert parent.api.should_retry(error)
