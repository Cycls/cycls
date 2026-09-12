"""cycls.MCP — a remote MCP server the agent connects to.

Client-side by default: the harness speaks Streamable HTTP itself, discovers
tools once (cached DISCOVERY_TTL seconds per url and token) and opens a
session only when a tool is called — so every provider gets MCP, and a turn
that uses no server costs nothing. `.server_side()` hands the server to the
Anthropic connector instead: fewer hops, one deploy-time bearer, anthropic/*
only. Immutable fluent, like cycls.LLM / cycls.Web / cycls.Image.
"""
import time
from typing import List, Optional
from .connectors import not_connected

DISCOVERY_TTL = 600
_discovered = {}   # (url, token) -> (deadline, [Tool])
_prompts = {}      # (url, token) -> (deadline, [Prompt])


def _session(url, headers):
    import httpx2
    from mcp.client.streamable_http import streamable_http_client
    return streamable_http_client(url, http_client=httpx2.AsyncClient(
        headers=headers, timeout=httpx2.Timeout(30.0, read=300.0)))


async def _list(url, headers):
    from mcp import ClientSession
    from mcp.types import PaginatedRequestParams
    tools, cursor = [], None
    async with _session(url, headers) as (r, w), ClientSession(r, w) as s:
        await s.initialize()
        while True:
            page = await s.list_tools(params=PaginatedRequestParams(cursor=cursor) if cursor else None)
            tools += page.tools
            if not (cursor := page.next_cursor):
                return tools


async def _list_prompts(url, headers):
    from mcp import ClientSession
    from mcp.types import PaginatedRequestParams
    prompts, cursor = [], None
    async with _session(url, headers) as (r, w), ClientSession(r, w) as s:
        await s.initialize()
        while True:
            page = await s.list_prompts(params=PaginatedRequestParams(cursor=cursor) if cursor else None)
            prompts += page.prompts
            if not (cursor := page.next_cursor):
                return prompts


async def _call(url, headers, name, args):
    from mcp import ClientSession
    async with _session(url, headers) as (r, w), ClientSession(r, w) as s:
        await s.initialize()
        return _shape(await s.call_tool(name, args))


def _shape(result):
    """Text blocks joined; `is_error` → `Error: …` so the loop and the model both see it."""
    blocks = getattr(result, "content", None) or []
    text = "\n".join(b.text for b in blocks if getattr(b, "text", None))
    if other := sum(1 for b in blocks if not getattr(b, "text", None)):
        text = f"{text}\n[{other} non-text block(s) omitted]".strip()
    if getattr(result, "is_error", False):
        return f"Error: {text or 'tool failed'}"
    return text or "(no output)"


class MCP:
    def __init__(self, url: str):
        self._url = url
        self._name: Optional[str] = None
        self._token: Optional[str] = None
        self._allow: Optional[List[str]] = None
        self._server_side = False
        self._connector = None
        self._guidance: Optional[str] = None
        self._writes = None

    def _copy(self, **updates):
        new = MCP.__new__(MCP)
        new.__dict__ = {**self.__dict__, **updates}
        if o := new._connector:   # the connector keeps its servers; a chained copy replaces the one it came from
            o.servers[:] = [new if s is self else s for s in o.servers] if self in o.servers else [*o.servers, new]
        return new

    def name(self, alias: str):
        """Label for this server — prefixes its tools and heads their step lines (default `mcp`)."""
        return self._copy(_name=alias)

    def token(self, bearer: str):
        """Bearer token sent to the MCP server (e.g. a GitHub PAT)."""
        return self._copy(_token=bearer)

    def allow(self, *tool_names: str):
        """Expose only these tools from the server (omit to expose all)."""
        return self._copy(_allow=list(tool_names))

    def server_side(self):
        """Let the Anthropic connector run this server — fewer hops, one
        deploy-time bearer, `anthropic/*` only."""
        return self._copy(_server_side=True)

    def guidance(self, text: str):
        """What the model should know before it reaches for this server — the argument shapes, the
        recipes, what not to do. Joins the system prompt whenever the server's tools are in the turn,
        so a question costs one call instead of a schema hunt."""
        return self._copy(_guidance=text)

    def writes(self, fn):
        """For a server that funnels everything through one tool (PostHog's `exec`): fn(tool, args) -> bool
        says whether *this call* writes. The tool defaults to *Ask*, but reads pass; only writes stop."""
        return self._copy(_writes=fn)

    def connector(self, oauth):
        """Send each call, and discovery, with the caller's grant for *oauth* (a cycls.Key or cycls.OAuth2).
        An OAuth server that lists anonymously shows its tools before anyone connects."""
        return self._copy(_connector=oauth)

    def _headers(self, token=None):
        tok = token or self._token
        return {"Authorization": f"Bearer {tok}"} if tok else {}

    async def prompts(self, token=None):
        """The server's prompt templates, if it offers any — cached like tools; a server without them reads as none."""
        key = (self._url, token or self._token)
        hit = _prompts.get(key)
        if not hit or hit[0] < time.monotonic():
            try:
                found = await _list_prompts(self._url, self._headers(token))
            except Exception:
                found = []
            _prompts[key] = hit = (time.monotonic() + DISCOVERY_TTL, found)
        return hit[1]

    @property
    def label(self):
        return self._name or "mcp"

    async def tools(self, token=None):
        """This server's tools (the SDK objects), discovered once per token and cached; `.allow()` applied."""
        key = (self._url, token or self._token)
        hit = _discovered.get(key)
        if not hit or hit[0] < time.monotonic():
            _discovered[key] = hit = (time.monotonic() + DISCOVERY_TTL, await _list(self._url, self._headers(token)))
        return [t for t in hit[1] if not self._allow or t.name in self._allow]

    async def discover(self, token=None):
        """(schemas, handlers, names) for this server's tools, prefixed `{name}_`."""
        schemas, handlers, names = [], {}, {}
        for t in await self.tools(token):
            full = f"{self.label}_{t.name}"
            schemas.append({"type": "custom", "name": full, "description": t.description or "",
                            "input_schema": t.input_schema})
            handlers[full] = self._handler(t.name)
            names[full] = f"{self.label} · {t.name}"
        return schemas, handlers, names

    def _handler(self, raw):
        async def call(inp, ctx):
            headers = self._headers()
            if self._connector:
                token = await self._connector.bearer(ctx.workspace)
                if not token:
                    return not_connected(self._connector.name)
                headers = {"Authorization": f"Bearer {token}"}
            return await _call(self._url, headers, raw, inp)
        return call

    def _spec(self) -> dict:
        """The Anthropic MCP-connector entry for this server."""
        spec: dict = {"type": "url", "url": self._url, "name": self._name or "mcp"}
        if self._token:
            spec["authorization_token"] = self._token
        if self._allow:
            spec["tool_configuration"] = {"allowed_tools": self._allow}
        return spec
