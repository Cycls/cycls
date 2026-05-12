"""cycls.MCP — a remote MCP server the agent connects to.

Consumption is server-side: the spec is passed through to the Anthropic
Messages API's MCP connector (`mcp_servers`, `anthropic-beta:
mcp-client-2025-04-04`). Anthropic does the connecting, tool discovery, and
tool-call round-trip; results come back in the stream as `mcp_tool_use` /
`mcp_tool_result` content blocks. So: HTTP/SSE remote servers only, and only
with `anthropic/*` models (the harness's OpenAI path is Chat Completions,
which has no MCP). Immutable fluent, like cycls.LLM / cycls.Web / cycls.Image.
"""
from typing import List, Optional


class MCP:
    def __init__(self, url: str):
        self._url = url
        self._name: Optional[str] = None
        self._token: Optional[str] = None
        self._allow: Optional[List[str]] = None

    def _copy(self, **updates):
        new = MCP.__new__(MCP)
        new.__dict__ = {**self.__dict__, **updates}
        return new

    def name(self, alias: str):
        """Label for this server — used to namespace its tools (default `mcp`)."""
        return self._copy(_name=alias)

    def token(self, bearer: str):
        """Bearer token sent to the MCP server (e.g. a GitHub PAT)."""
        return self._copy(_token=bearer)

    def allow(self, *tool_names: str):
        """Expose only these tools from the server (omit to expose all)."""
        return self._copy(_allow=list(tool_names))

    def _spec(self) -> dict:
        """The Anthropic MCP-connector entry for this server."""
        spec: dict = {"type": "url", "url": self._url, "name": self._name or "mcp"}
        if self._token:
            spec["authorization_token"] = self._token
        if self._allow:
            spec["tool_configuration"] = {"allowed_tools": self._allow}
        return spec
