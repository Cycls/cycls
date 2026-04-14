# uv run examples/agent/super-openai.py
#
# Requires: OPENAI_API_KEY in env, `openai` package installed.
# Routes through cycls/agent/openai.py (Chat Completions adapter).

import cycls

SYSTEM = """
You are Cycls, running on GPT-5.4.
""".strip()


TOOLS = [
    {
        "name": "render_image",
        "description": "Display an image to the user.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "src": {"type": "string", "description": "Image URL or path"},
                "alt": {"type": "string"},
                "caption": {"type": "string"},
            },
            "required": ["src"],
        },
    }
]


@cycls.agent(
    auth=True,
    analytics=True,
    plan="cycls_pass",
    copy=[".env"],
    pip=["openai"],
    force_rebuild=False,
    title="Cycls on GPT-5.4",
)
async def super_openai(context):
    async for msg in cycls.Agent(
        context=context,
        system=SYSTEM,
        tools=TOOLS,
        builtin_tools=["Bash", "Editor"],  # WebSearch omitted — OpenAI-adapter drops Anthropic server tools
        model="openai/gpt-5.4",             # provider/model → routed to OpenAI Chat Completions adapter
        show_usage=True,
    ):
        yield msg


super_openai.local()
# super_openai.deploy()
