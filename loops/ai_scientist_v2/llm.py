"""Interface with the underlying model"""

import base64
import json
import os

import litellm

from ai_scientist_v2 import prompts

# Room for a full experiment script and its plan, which can pass 8k tokens
_MAX_TOKENS = 32000


class BudgetExceeded(Exception):
    """The run key's budget or time is spent, so the gateway refuses model calls."""


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
        model: Model name as configured in the LiteLLM gateway.
        messages: List of messages to send to the model.
        tools: List of tools available to the model.
        tool_choice: Optional tool choice to force the model to use a specific tool.
    ReturnS:
        The model's reply message.

    Raises:
        BudgetExceeded: The run key's budget is spent, or the key has expired.
        RuntimeError: The reply was cut off at `_MAX_TOKENS`.
    """
    try:
        response = litellm.completion(
            model=f"litellm_proxy/{model}",
            api_base=os.environ["OPENAI_BASE_URL"],
            api_key=os.environ["ANTHROPIC_AUTH_TOKEN"],
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
        raise RuntimeError(f"The model's reply was cut off at {_MAX_TOKENS} tokens.")
    return response.choices[0].message


def call_tool(model: str, messages: list[dict], tool: dict) -> dict:
    """
    Asks the model to call one tool, and returns json.loads of its arguments.

    Some models, e.g. Opus 5.5, reject a forced tool_choice, so a system message asks
    for the call instead.

    Args:
        model: Model name as configured in the LiteLLM gateway.
        messages: List of messages to send to the model.
        tool: Tool definition
                {"type": "function", "function": {name, description, parameters}}.

    Returns:
        json.loads of the tool's arguments, as returned by the model.
    """
    name = tool["function"]["name"]
    system = {"role": "system", "content": prompts.CALL_TOOL.format(name=name)}
    message = query(model, [system, *messages], tools=[tool], tool_choice="auto")
    if not message.tool_calls:
        raise ValueError(f"Model replied without calling `{name}`: {message.content}")
    return json.loads(message.tool_calls[0].function.arguments)


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
