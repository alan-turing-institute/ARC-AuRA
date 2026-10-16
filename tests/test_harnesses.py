import json

from aura.harnesses import opencode


def test_opencode_uses_mcp_json_servers_and_run_model(tmp_path, monkeypatch):
    mcp = {"mcpServers": {"lit": {"type": "http", "url": "http://litmcp:8000/mcp"}}}
    (tmp_path / "mcp.json").write_text(json.dumps(mcp))
    monkeypatch.setattr(opencode, "MCP_CONFIG", tmp_path / "mcp.json")

    command = opencode.opencode_command("Do the task.", "claude-haiku-4-5")

    config = json.loads(command[1].removeprefix("OPENCODE_CONFIG_CONTENT="))
    assert config["mcp"] == {"lit": {"type": "remote", "url": "http://litmcp:8000/mcp"}}
    assert command[command.index("--model") + 1] == "anthropic/claude-haiku-4-5"
