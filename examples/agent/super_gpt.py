# conda activate cycls && python examples/agent/super_gpt.py
import sys, os; sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))
import cycls

SYSTEM = """
You are a super agent powered by GPT-5.4 — OpenAI's most capable model with built-in web search.
You excel at coding, reasoning, tool use, and multi-step problem solving.
""".strip()

@cycls.app(auth=True, analytics=True, copy=[".env"], force_rebuild=False)
async def super_gpt(context):
    async for msg in cycls.Agent(
        context=context,
        system=SYSTEM,
        builtin_tools=["Bash", "Editor", "WebSearch"],
        model="openai/gpt-5.4",
        max_tokens=16384,
        thinking=True,
        show_usage=True,
    ):
        yield msg


super_gpt.local()
