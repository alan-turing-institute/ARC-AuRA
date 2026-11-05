"""Interface with the underlying model"""

import base64
import json

import litellm

from ai_scientist_v2 import prompts

# Room for a full experiment script and its plan, which can pass 8k tokens
_MAX_TOKENS = 32000
_BRIDGE_URL = "http://localhost:13131/v1"  # Inspect model bridge, configure?


class BudgetExceeded(Exception):
    """The run key's budget or time is spent, so the gateway refuses model calls."""


class ModelReplyError(Exception):
    """The model's reply is unusable: cut off, missing its tool call, or bad JSON."""


def query(
    model: str,
    messages: list[dict],
    tools: list[dict] | None = None,
    tool_choice=None,
) -> "litellm.Message":
    """
    Query the run model with a list of messages, and optional tool calls through the
    gateway; return its reply.

    Args:
        model: Model name as configured in the LiteLLM gateway; calls go via Inspect's
                bridge.
        messages: List of messages to send to the model.
        tools: List of tools available to the model.
        tool_choice: Optional tool choice to force the model to use a specific tool.
    ReturnS:
        The model's reply message.

    Raises:
        BudgetExceeded: The run key's budget is spent, or the key has expired.
        ModelReplyError: The reply was cut off at `_MAX_TOKENS`.
    """
    try:
        response = litellm.completion(
            model=f"openai/{model}",
            api_base=_BRIDGE_URL,
            api_key="unused",  # the bridge ignores it; the host's call adds the run key.
            messages=messages,
            tools=tools,
            tool_choice=tool_choice,
            max_tokens=_MAX_TOKENS,
            num_retries=3,
        )
    except (litellm.RateLimitError, litellm.AuthenticationError) as e:
        # The gateway's messages for a spent budget and an expired run key
        if "Budget has been exceeded" in str(e) or "Expired Key" in str(e):
            raise BudgetExceeded(str(e)) from e
        raise
    if response.choices[0].finish_reason == "length":
        raise ModelReplyError(f"The model's reply was cut off at {_MAX_TOKENS} tokens.")
    return response.choices[0].message


def call_tool(model: str, messages: list[dict], tool: dict) -> dict:
    """
    Asks the model to call one tool, and returns json.loads of its arguments.

    Some models, e.g. Opus 5.5, reject a forced tool_choice, so a final user message
    asks for the call instead; last, so it follows any instruction in `messages`.

    Args:
        model: Model name as configured in the LiteLLM gateway.
        messages: List of messages to send to the model.
        tool: Tool definition
                {"type": "function", "function": {name, description, parameters}}.

    Returns:
        json.loads of the tool's arguments, as returned by the model.

    Raises:
        ModelReplyError: The reply doesn't call the tool, or its arguments aren't JSON.
    """
    name = tool["function"]["name"]
    ask = {"role": "user", "content": prompts.CALL_TOOL.format(name=name)}
    message = query(model, [*messages, ask], tools=[tool], tool_choice="auto")
    calls = message.tool_calls or []
    matching = [c for c in calls if c.function.name == name]
    if not matching:
        called = [c.function.name for c in calls]
        raise ModelReplyError(
            f"Model didn't call `{name}` (called {called}): {message.content}"
        )
    try:
        return json.loads(matching[0].function.arguments)
    except json.JSONDecodeError as e:
        raise ModelReplyError(f"`{name}` arguments aren't valid JSON: {e}") from e


def image_contents(path: str) -> dict:
    """
    Reads the contents of an image file and returns a dictionary with the
    base64-encoded contents.

    Args:
        path: Path to the image file.
    Returns:
        Dictionary with the base64-encoded contents of the image file.
    """
    with open(path, "rb") as f:
        data = base64.b64encode(f.read()).decode()
    return {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{data}"}}
