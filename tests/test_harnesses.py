import json

from aura.harnesses import ai_scientist_v2, mcp


def test_mcp_servers_reads_mcp_json(tmp_path, monkeypatch):
    servers = {"mcpServers": {"lit": {"type": "http", "url": "http://litmcp:8000/mcp"}}}
    (tmp_path / "mcp.json").write_text(json.dumps(servers))
    monkeypatch.setattr(mcp, "MCP_CONFIG", tmp_path / "mcp.json")

    (server,) = mcp.mcp_servers()

    assert (server.name, server.url) == ("lit", "http://litmcp:8000/mcp")


def test_ai_scientist_v2_passes_model_and_stages():
    command = ai_scientist_v2.ai_scientist_v2_command(
        "Do the task.", "claude-opus-5-5", ["lit_review", "report"]
    )

    assert command[:6] == [
        "env", "PYTHONPATH=/loops", "python", "-m", "ai_scientist_v2", "Do the task."
    ]  # fmt: skip
    assert command[command.index("--model") + 1] == "claude-opus-5-5"
    assert command[command.index("--stages") + 1 :] == ["lit_review", "report"]
