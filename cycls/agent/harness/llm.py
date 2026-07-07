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
        self._max_tokens = None   # None = 8k default
        self._context = None      # None = 1M default
        self._price = None
        self._bash_timeout = 600
        self._bash_network = True
        self._base_url = None
        self._api_key = None
        self._handlers = {}
        self._mcp = []
        self._loop = None
        self._thinking = "adaptive"
        self._web_search = "brave"
        self._instructions = "AGENT.md"
        self._skills = []

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
    def context(self, n):
        """Model context window in tokens — sets when compaction kicks in."""
        return self._copy(_context=n)
    def price(self, *, input=0.0, output=0.0, cache_read=0.0, cache_write=0.0):
        """Token prices in USD per 1M, for cost tracking. Unset → costs report as $0."""
        return self._copy(_price=(input, output, cache_read, cache_write))
    def bash_timeout(self, secs):   return self._copy(_bash_timeout=secs)
    def sandbox(self, *, network=True):
        """Configure the bash sandbox. Network is ON by default; pass
        network=False when the agent doesn't need curl/pip/git — a
        prompt-injected bash can exfiltrate anything it can read."""
        return self._copy(_bash_network=network)
    def base_url(self, url):        return self._copy(_base_url=url)
    def api_key(self, key):         return self._copy(_api_key=key)
    def on(self, name, handler):
        """Register an async handler for a custom tool by name. The handler's
        return value is both yielded to the stream (body sees it as a normal
        event) and packaged as the tool_result sent back to the model."""
        return self._copy(_handlers={**self._handlers, name: handler})

    def instructions(self, path):
        """Workspace instructions file auto-loaded into the system prompt each
        turn (default "AGENT.md" at the workspace root, capped at 24KB).
        Pass None to disable."""
        return self._copy(_instructions=path)

    def skills(self, *sources):
        """Ship skills with the agent: each source is a directory of skill
        folders (<name>/SKILL.md + support files), or a single skill folder.
        Shipped skills are read-only — their dirs mount at /skills/<name> in
        the bash sandbox. User workspace skills (skills/<name>/SKILL.md) are
        always discovered and win name collisions. `.skills(None)` disables
        skills entirely. `skill` is a reserved tool name."""
        if sources == (None,): return self._copy(_skills=None)
        return self._copy(_skills=[*(self._skills or []), *sources])

    def mcp(self, *servers):
        """Connect to one or more remote MCP servers (cycls.MCP). Their tools
        run server-side via the Anthropic MCP connector — anthropic/* only."""
        return self._copy(_mcp=[*self._mcp, *servers])

    def thinking(self, spec):
        """Reasoning control, mapped per provider. `"adaptive"` (default) lets
        the model decide; `"low"|"medium"|"high"` sets a unified effort level
        (Anthropic `effort`, OpenAI/Gemini `reasoning_effort`); None disables
        where the provider allows it (GLM). An int is a legacy Anthropic
        token budget. Auto-disabled on models without thinking (Haiku)."""
        return self._copy(_thinking=spec)

    def web_search(self, mode="brave"):
        """Web search backend when `WebSearch` is allowed. `"brave"` (default) is
        our portable search + fetch pair — works on any model and needs
        `BRAVE_API_KEY`; without the key it falls back to the provider's native
        search where one exists. `"native"` forces the provider's server-side
        search (Anthropic only, for now; skipped with a warning elsewhere)."""
        return self._copy(_web_search=mode)

    def loop(self, fn):
        """Run a custom loop instead of the built-in one. `fn` is an async
        generator with the default loop's signature (context, system, tools,
        allowed_tools, model, max_tokens, ..., handlers, mcp_servers,
        instructions, skills) that yields `Event`s — accept `**kw` to stay
        compatible as kwargs are added. Building blocks live in `cycls.agent.harness`:
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
            client=client,
            base_url=self._base_url,
            api_key=self._api_key,
            handlers=self._handlers,
            mcp_servers=self._mcp,
            thinking=self._thinking,
            web_search=self._web_search,
            instructions=self._instructions,
            skills=self._skills,
            price=self._price,
            context_window=self._context,
        ):
            yield ev
