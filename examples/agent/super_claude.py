# conda activate cycls && python examples/agent/super_claude.py
import sys, os; sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))
import cycls

SYSTEM = """
You are a super agent powered by Claude Opus 4.6 — Anthropic's most capable model.
You excel at complex reasoning, coding, research, and multi-step problem solving.
""".strip()

@cycls.app(auth=True, analytics=True, copy=[".env"], force_rebuild=False)
async def super_claude(context):
    async for msg in cycls.Agent(
        context=context,
        system=SYSTEM,
        builtin_tools=["Bash", "Editor", "WebSearch"],
        model="anthropic/claude-opus-4-6",
        max_tokens=16384,
        thinking=True,
        show_usage=True,
    ):
        yield msg


super_claude.local()
