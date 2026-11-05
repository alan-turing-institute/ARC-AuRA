from collections.abc import Callable

from inspect_ai.agent import Agent

from aura.harnesses.ai_scientist_v2 import ai_scientist_v2_command
from aura.harnesses.claude_code import claude_code_agent
from aura.harnesses.opencode import opencode_agent

# Builds an Inspect agent for a harness, given the LiteLLM model name
Harness = Callable[[str], Agent]

HARNESSES: dict[str, Harness] = {
    "claude-code": claude_code_agent,
    "opencode": opencode_agent,
    "ai-scientist-v2": ai_scientist_v2_command,
}
