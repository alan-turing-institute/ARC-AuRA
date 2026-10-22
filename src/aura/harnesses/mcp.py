import json

from inspect_ai.tool import MCPServerConfigHTTP

from aura.constants import MCP_CONFIG


def mcp_servers() -> list[MCPServerConfigHTTP]:
    """Load the MCP servers in `mcp.json` as Inspect server configs."""
    servers = json.loads(MCP_CONFIG.read_text())["mcpServers"]
    return [MCPServerConfigHTTP(name=name, **s) for name, s in servers.items()]
