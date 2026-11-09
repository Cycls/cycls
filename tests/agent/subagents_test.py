"""Agents a run hands work to (cycls/_agent/tools/agent.py, docs/rfc-subagents.md): they work in the background,
the parent waits for their reports instead of ending, at most four work at once, and two never write one file."""
import asyncio
from unittest.mock import MagicMock

from cycls._agent.harness.llm import LLM
from cycls._agent.harness.events import to_ui
from cycls._agent.state import get_agents, get_meta, load_messages
from cycls._agent.tools.agent import BRIEFED, Team
from agent_test import FakeStream, _make_context, _make_response, _text_block, _tool_use_block


def _llm():
    return LLM().model("anthropic/claude-test").allowed_tools(["Agent", "Editor", "Ask"]).price(input=1, output=1)


def _client(parent, child, seen=None):
    """One fake model for the parent and its agents: an agent's requests carry the brief's preamble."""
    parent, child = iter(parent), iter(child)
    client = MagicMock()
    def stream(**kw):
        agent = BRIEFED in str(kw.get("system"))
        if seen is not None: seen.append(("agent" if agent else "parent", kw))
        return FakeStream(next(child if agent else parent))
    client.messages.stream = stream
    return client


def _agent(call, label="Research prices", brief="Find the delivery fees"):
    return _tool_use_block(call, "agent", {"description": label, "prompt": brief})


async def _drain(gen):
    return [to_ui(ev) async for ev in gen]


def test_an_agent_works_in_the_background_and_its_report_wakes_the_parent(tmp_path):
    ctx = _make_context(tmp_path / "ws")
    client = _client(
        parent=[_make_response([_agent("a1")], stop_reason="tool_use"),
                _make_response([_text_block("Jahez is 19 SAR.")])],
        child=[_make_response([_text_block("Jahez Plus is 19 SAR a month.")])])

    evs = asyncio.run(_drain(_llm().run(context=ctx, client=client)))

    done = [e["agent"] for e in evs if isinstance(e, dict) and e.get("id") == "a1" and "agent" in e]
    assert done[-1]["status"] == "done" and done[-1]["report"] == "Jahez Plus is 19 SAR a month."
    history = asyncio.run(load_messages(ctx.workspace, ctx.chat_id))
    report = next(m for m in history if m.get("internal"))
    assert '<agent-report label="Research prices" status="done">' in report["content"]
    assert history[-1]["content"][0]["text"] == "Jahez is 19 SAR."
    assert asyncio.run(get_agents(ctx.workspace, ctx.chat_id))["a1"]["status"] == "done"
    # the parent's two turns, the second only once the report is in, and the agent's one: 600 tokens each at $1/M
    assert float(asyncio.run(get_meta(ctx.workspace, ctx.chat_id))["cost"]) == 3 * 600 / 1_000_000


def test_an_agent_cannot_start_agents_or_ask_the_person(tmp_path):
    seen = []
    client = _client(parent=[_make_response([_agent("a1")], stop_reason="tool_use"), _make_response([_text_block("ok")]),
                             _make_response([_text_block("ok")])],
                     child=[_make_response([_text_block("done")])], seen=seen)
    asyncio.run(_drain(_llm().run(context=_make_context(tmp_path / "ws"), client=client)))
    names = {who: {t["name"] for t in kw["tools"]} for who, kw in seen}
    assert {"agent", "ask"} <= names["parent"]
    assert not {"agent", "ask"} & names["agent"] and "edit" in names["agent"]


def test_at_most_four_work_at_once(tmp_path):
    ctx = _make_context(tmp_path / "ws")
    seen = []
    client = _client(parent=[_make_response([_agent(f"a{i}") for i in range(5)], stop_reason="tool_use"),
                             *[_make_response([_text_block("ok")]) for _ in range(5)]],
                     child=[_make_response([_text_block("done")]) for _ in range(4)], seen=seen)
    asyncio.run(_drain(_llm().run(context=ctx, client=client)))
    results = {b["tool_use_id"]: b["content"] for m in asyncio.run(load_messages(ctx.workspace, ctx.chat_id))
               if isinstance(m["content"], list) for b in m["content"] if b.get("type") == "tool_result"}
    assert results["a4"].startswith("Error: 4 agents are already working")
    assert sum(who == "agent" for who, _ in seen) == 4


def test_two_agents_never_write_one_file():
    team = Team(None, None, None)
    team.agents = {"c1": {"label": "Draft the sheet"}, "c2": {"label": "Other"}}
    assert team.refuse("sheets", {"action": "edit", "path": "pricing.xlsx"}, "c1") is None
    assert "being worked on by «Draft the sheet»" in team.refuse("edit", {"path": "/pricing.xlsx"}, "c2")
    assert team.refuse("edit", {"path": "pricing.xlsx"}, None).startswith("Error")   # the parent too
    assert team.refuse("read", {"path": "pricing.xlsx"}, None).startswith("Error")   # nor read half made
    assert team.refuse("sheets", {"action": "read", "path": "pricing.xlsx"}, "c1") is None
    assert team.refuse("read", {"path": "notes.md"}, "c2") is None
    # a design is held by its name, as its file
    assert team.refuse("design", {"action": "edit", "name": "pitch"}, "c1") is None
    assert team.refuse("read", {"path": "pitch.fig"}, None).startswith("Error")
    assert team.refuse("design", {"action": "inspect", "name": "pitch.fig"}, "c2").startswith("Error")
    assert team.refuse("design", {"action": "skill", "name": "deck-design"}, "c2") is None


def test_each_agent_browses_in_its_own_browser(monkeypatch):
    from cycls._agent import tools
    seen = []
    async def browse(inp, ws, chat_id=None):
        seen.append(chat_id)
    monkeypatch.setattr(tools, "_exec_browser", browse)
    for ctx in (tools.ToolContext(None, None, "chat1"), tools.ToolContext(None, None, None, me="a1")):
        asyncio.run(tools._TOOLS["browser"].run({}, None, ctx=ctx))
    assert seen == ["chat1", "a1"]


class _Slow(FakeStream):
    def __init__(self, response, wait):
        super().__init__(response)
        self.wait = wait

    async def get_final_message(self):
        await asyncio.sleep(self.wait)
        return self._response


def test_a_report_reaches_the_parent_at_its_next_step(tmp_path):
    """The slow agent ends while the parent is mid-turn: the parent's next step knows, it isn't told at the end."""
    parent = iter([(_make_response([_agent("a1", "Fast", "fast brief"), _agent("a2", "Slow", "slow brief")],
                                   stop_reason="tool_use"), 0),
                   (_make_response([_tool_use_block("e1", "edit", {"command": "create", "path": "n.md", "file_text": "x"})],
                                   stop_reason="tool_use"), 0.5),
                   (_make_response([_text_block("Both are done.")]), 0)])
    seen = []
    client = MagicMock()
    def stream(**kw):
        if BRIEFED in str(kw.get("system")):
            return _Slow(_make_response([_text_block("done")]), 0.3 if "slow brief" in str(kw["messages"]) else 0)
        seen.append(kw)
        return _Slow(*next(parent))
    client.messages.stream = stream
    asyncio.run(_drain(_llm().run(context=_make_context(tmp_path / "ws"), client=client)))
    assert 'label="Slow"' in str(seen[2]["messages"]) and len(seen) == 3
