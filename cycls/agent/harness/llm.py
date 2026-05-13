"""cycls.LLM — fluent immutable builder for agent loop configuration.

Holds all settings that define how an agent runs: model, system prompt, tools,
allowed builtins, token limits, provider credentials, runtime knobs. Call
`.run(context=...)` to execute the loop — `context` is the only runtime input.

`.run` yields typed `Event`s (see `cycls.agent.harness.events`): the agent body
`to_ui`s them through, or pattern-matches first to hook the loop. `.loop(fn)`
swaps in a different loop entirely (the building blocks — `make_provider`,
`Session`, `build_tools`, `dispatch`, `compact`, `events` — live in
`cycls.agent.harness`).

Everything else lives on the builder. State is where you built it, not where
you invoked it.
"""


class LLM:
    def __init__(self):
        self._model = None
        self._system = ""
        self._tools = []
        self._allowed_tools = []
        self._max_tokens = 16384
        self._bash_timeout = 600
        self._bash_network = True
        self._show_usage = False
        self._base_url = None
        self._api_key = None
        self._handlers = {}
        self._mcp = []
        self._loop = None
        self._thinking = "adaptive"

    def _copy(self, **updates):
        new = LLM.__new__(LLM)
        new.__dict__ = {**self.__dict__, **updates}
        return new

    # ---- Fluent builders ----

    def model(self, name):          return self._copy(_model=name)
    def system(self, text):         return self._copy(_system=text)
    def tools(self, tools):         return self._copy(_tools=list(tools))
    def allowed_tools(self, names): return self._copy(_allowed_tools=list(names))
    def max_tokens(self, n):        return self._copy(_max_tokens=n)
    def bash_timeout(self, secs):   return self._copy(_bash_timeout=secs)
    def sandbox(self, *, network=True):
        """Configure the bash sandbox. Network is OFF by default — enabling it
        allows curl/pip/git but lets a compromised bash exfiltrate over the wire."""
        return self._copy(_bash_network=network)
    def show_usage(self, on=True):  return self._copy(_show_usage=on)
    def base_url(self, url):        return self._copy(_base_url=url)
    def api_key(self, key):         return self._copy(_api_key=key)
    def on(self, name, handler):
        """Register an async handler for a custom tool by name. The handler's
        return value is both yielded to the stream (body sees it as a normal
        event) and packaged as the tool_result sent back to the model."""
        return self._copy(_handlers={**self._handlers, name: handler})

    def mcp(self, *servers):
        """Connect to one or more remote MCP servers (cycls.MCP). Their tools
        run server-side via the Anthropic MCP connector — anthropic/* only."""
        return self._copy(_mcp=[*self._mcp, *servers])

    def thinking(self, spec):
        """Set the model's thinking budget. `"adaptive"` (default) lets the
        model decide — auto-disabled on models that don't support it (Haiku).
        Pass an int for an explicit budget in tokens, or None to disable.
        Anthropic-only — OpenAI providers ignore this."""
        return self._copy(_thinking=spec)

    def loop(self, fn):
        """Run a custom loop instead of the built-in one. `fn` is an async
        generator with the default loop's signature (context, system, tools,
        allowed_tools, model, max_tokens, ..., handlers, mcp_servers) that
        yields `Event`s. Building blocks live in `cycls.agent.harness`:
        `default_loop`, `make_provider`, `Session`, `build_tools`, `dispatch`,
        `compact`, `events`."""
        return self._copy(_loop=fn)

    # ---- Execution ----

    async def run(self, *, context, client=None):
        """Run the agent loop with this LLM's configuration, yielding `Event`s.

        `context` is the per-invocation input (messages, user, session).
        `client` is a test-only seam for injecting a mocked provider.
        """
        if self._model is None:
            raise ValueError("LLM.model(...) is required before .run()")
        from .main import _run
        loop = self._loop or _run
        async for ev in loop(
            context=context,
            system=self._system,
            tools=self._tools,
            allowed_tools=self._allowed_tools,
            model=self._model,
            max_tokens=self._max_tokens,
            bash_timeout=self._bash_timeout,
            bash_network=self._bash_network,
            show_usage=self._show_usage,
            client=client,
            base_url=self._base_url,
            api_key=self._api_key,
            handlers=self._handlers,
            mcp_servers=self._mcp,
            thinking=self._thinking,
        ):
            yield ev
