"""Interface with the underlying model"""

import base64
import json
import os

import litellm


class BudgetExceeded(Exception):
    """The run key's budget is spent, so the gateway refuses further model calls."""


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
    """
    try:
        response = litellm.completion(
            model=f"litellm_proxy/{model}",
            api_base=os.environ["OPENAI_BASE_URL"],
            api_key=os.environ["ANTHROPIC_AUTH_TOKEN"],
            messages=messages,
            tools=tools,
            tool_choice=tool_choice,
            max_tokens=8192,
            num_retries=3,
        )
    except litellm.RateLimitError as e:
        if "Budget has been exceeded" in str(e):
            raise BudgetExceeded(str(e)) from e
        raise
    return response.choices[0].message


def call_tool(model: str, messages: list[dict], tool: dict) -> dict:
    """
    Forces one function call with tool_choice, and returns json.loads of it arguments.

    Args:
        model: Model name as configured in the LiteLLM gateway.
        messages: List of messages to send to the model.
        tool: Tool definition
                {"type": "function", "function": {name, description, parameters}}.

    Returns:
        json.loads of the tool's arguments, as returned by the model.
    """
    choice = {"type": "function", "function": {"name": tool["function"]["name"]}}
    message = query(model=model, messages=messages, tools=[tool], tool_choice=choice)
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
