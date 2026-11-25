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
