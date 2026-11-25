"""What a turn waited for before its first model call (super-dev `prelude` log, 2026-11-25): the model's SDK
loading on a server's first turn (~2.3 s), and connector tool lists asked again before the turn once they
expired (~2.3 s). Neither holds a turn now; the steps that remain are logged."""
import asyncio, sys, threading, time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import cycls
from cycls._agent import mcp as m, prelude
from cycls._agent.harness import providers


def test_the_models_sdk_loads_as_the_agent_is_defined_on_a_server_only(monkeypatch):
    started = []

    class Thread:
        def __init__(self, target, name, daemon):
            started.append(name)

        def start(self):
            pass
    monkeypatch.setattr(threading, "Thread", Thread)
    monkeypatch.setattr(providers, "_warming", set())
    monkeypatch.delitem(sys.modules, "openai", raising=False)   # put back as it was after the test
    monkeypatch.delenv("K_REVISION", raising=False)
    cycls.LLM().model("openrouter/deepseek/deepseek-v4.1-flash")
    assert started == []                                          # not here: tests swap fake SDKs in
    monkeypatch.setenv("K_REVISION", "super-dev-00042")
    cycls.LLM().model("openrouter/deepseek/deepseek-v4.1-flash")
    cycls.LLM().model("openai/gpt-5.4")
    assert started == ["warm-openai"]                             # once, on a server
    cycls.LLM().model("anthropic/claude-sonnet-5-5")
    assert started == ["warm-openai", "warm-anthropic"]


def _tool(name):
    return SimpleNamespace(name=name, description="", input_schema={"type": "object"})


def test_a_server_restoring_the_agent_makes_its_client_and_fetches_the_lists_everyone_shares(monkeypatch):
    """The agent reaches its server pickled: `.model()` never runs there, `__setstate__` does."""
    import cloudpickle
    from cycls._agent import connectors as c
    from tests.agent.connectors_test import _google

    class Thread:   # runs its work at once, so the test sees it done
        def __init__(self, target, name, daemon):
            self.target = target

        def start(self):
            self.target()
    monkeypatch.setattr(threading, "Thread", Thread)
    monkeypatch.setattr(providers, "_warming", set())
    made = []
    monkeypatch.setattr(providers, "_client_for", lambda vendor, **kw: made.append((vendor, kw)))
    m._discovered.clear()
    c._refused.clear()

    async def listing(url, headers):
        if "refuses" in url:
            raise RuntimeError("401")
        return [_tool("search")]
    monkeypatch.setattr(m, "_list", listing)
    llm = (cycls.LLM().model("openrouter/deepseek/deepseek-v4.1-flash").base_url("https://openrouter.ai/api/v1")
           .api_key("k").mcp(cycls.MCP("https://tools.example/mcp"),
                             cycls.MCP("https://refuses.example/mcp").connector(_google())))
    shipped = cloudpickle.dumps(llm)
    monkeypatch.delenv("K_REVISION", raising=False)
    cloudpickle.loads(shipped)
    assert made == [] and not m._discovered                                    # not off a server
    monkeypatch.setenv("K_REVISION", "super-dev-00042")
    cloudpickle.loads(shipped)
    assert made == [("openrouter", {"base_url": "https://openrouter.ai/api/v1", "api_key": "k", "headers": None})]
    assert [t.name for t in m._discovered[("https://tools.example/mcp", None)][1]] == ["search"]
    assert c._refused["https://refuses.example/mcp"] > time.monotonic()        # off until it lists, as a turn finds it
    c._refused.clear()


def test_an_expired_tool_list_answers_the_turn_and_is_asked_again_behind_it(monkeypatch):
    m._discovered.clear()
    server = cycls.MCP("https://tools.example/mcp")
    key = ("https://tools.example/mcp", None)
    m._discovered[key] = (time.monotonic() - 1, [_tool("old")])   # expired a second ago
    listing = AsyncMock(return_value=[_tool("new")])
    monkeypatch.setattr(m, "_list", listing)

    async def turn():
        got = [t.name for t in await server.tools()]
        waited = listing.await_count
        await asyncio.gather(*m._background)
        return got, waited
    got, waited = asyncio.run(turn())
    assert got == ["old"] and waited == 0                         # the turn didn't wait for the server
    assert [t.name for t in m._discovered[key][1]] == ["new"]     # the next one has the new list
    assert m._discovered[key][0] > time.monotonic()


def test_a_server_that_cant_answer_loses_its_list_so_the_next_turn_asks_it_itself(monkeypatch):
    m._discovered.clear()
    server = cycls.MCP("https://down.example/mcp")
    key = ("https://down.example/mcp", None)
    m._discovered[key] = (time.monotonic() - 1, [_tool("old")])
    monkeypatch.setattr(m, "_list", AsyncMock(side_effect=RuntimeError("503")))

    async def turn():
        got = await server.tools()
        await asyncio.gather(*m._background)
        return got
    assert [t.name for t in asyncio.run(turn())] == ["old"]
    assert key not in m._discovered


def test_a_list_too_old_to_trust_is_asked_for_before_the_turn(monkeypatch):
    m._discovered.clear()
    server = cycls.MCP("https://tools.example/mcp")
    key = ("https://tools.example/mcp", None)
    m._discovered[key] = (time.monotonic() - m.STALE_FOR - 1, [_tool("ancient")])
    monkeypatch.setattr(m, "_list", AsyncMock(return_value=[_tool("new")]))
    assert [t.name for t in asyncio.run(server.tools())] == ["new"]


def test_the_steps_before_the_first_call_are_taken_once():
    prelude.start()
    prelude.mark("chat history read")
    prelude.mark("skills")
    prelude.mark("skills")
    steps, total = prelude.take()
    assert set(steps) == {"chat history read", "skills"} and total >= 0
    assert prelude.take() is None                                 # logged once per run
    prelude.mark("design outline")                                # a later mark alone says nothing
    assert prelude.take() is None
