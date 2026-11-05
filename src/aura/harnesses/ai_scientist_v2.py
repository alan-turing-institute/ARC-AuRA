from inspect_ai.agent import Agent, AgentState, agent, sandbox_agent_bridge
from inspect_ai.util import sandbox


def loop_command(prompt: str, model: str, stages: list[str]) -> list[str]:
    """Build the loop's command; the prompt goes before `--stages`, which takes all
    the arguments after it."""
    return [
        "python", "-m", "ai_scientist_v2", prompt,
        "--model", model, "--stages", *stages,
    ]  # fmt: skip


@agent
def ai_scientist_v2_agent(model: str, stages: list[str]) -> Agent:
    """
    Build an agent that runs the AI Scientist-v2 loop, mounted at /loops.

    The loop calls models through Inspect's bridge, which forwards its generation
    settings, such as max_tokens.

    Args:
        model: Model name as configured in the LiteLLM gateway.
        stages: Names from `STAGES` to produce outputs for.

    Returns:
        The agent, to use as an Inspect solver.
    """

    async def execute(state: AgentState) -> AgentState:
        command = loop_command(state.messages[0].text, model, stages)
        async with sandbox_agent_bridge(
            state, forward_generation_config=True
        ) as bridge:
            result = await sandbox().exec(command, env={"PYTHONPATH": "/loops"})
        if not result.success:
            raise RuntimeError(f"AI Scientist-v2 failed: {result.stderr[-2000:]}")
        return bridge.state

    return execute
