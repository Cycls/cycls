# conda activate cycls && python examples/agent/super_gemini.py
import sys, os; sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))
import cycls

SYSTEM = """
You are a super agent powered by Gemini 3.1 Pro — Google's most capable model.
You excel at complex reasoning, scientific analysis, coding, and research with 2M token context.
""".strip()

@cycls.app(auth=True, analytics=True, copy=[".env"], force_rebuild=False)
async def super_gemini(context):
    async for msg in cycls.Agent(
        context=context,
        system=SYSTEM,
        builtin_tools=["Bash", "Editor", "WebSearch"],
        model="gemini/gemini-3.1-pro-preview",
        max_tokens=16384,
        thinking=True,
        show_usage=True,
    ):
        yield msg


super_gemini.deploy()
