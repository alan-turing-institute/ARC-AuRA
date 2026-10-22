import json

from aura.harnesses import mcp


def test_mcp_servers_reads_mcp_json(tmp_path, monkeypatch):
    servers = {"mcpServers": {"lit": {"type": "http", "url": "http://litmcp:8000/mcp"}}}
    (tmp_path / "mcp.json").write_text(json.dumps(servers))
    monkeypatch.setattr(mcp, "MCP_CONFIG", tmp_path / "mcp.json")

    (server,) = mcp.mcp_servers()

    assert (server.name, server.url) == ("lit", "http://litmcp:8000/mcp")
