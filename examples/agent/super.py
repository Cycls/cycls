# uv run examples/agent/super.py
# cd client && npm run dev
# uv run pytest tests/agent_test.py -v

import cycls

SYSTEM = """
You are Cycls.
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
                "caption": {"type": "string"}
            },
            "required": ["src"]
        }
    }
]


@cycls.agent(
    auth=True,      # web/config
    analytics=True, # web=["Auth", "Analytics"]
    plan="cycls_pass",
    copy=[".env"],
    force_rebuild=False,
    title="The agent for getting things done"
)
async def super(context):
    # yield f"{context.user.plan}\n\n"
    # print(context.messages.raw)
    async for msg in cycls.Agent(
                                context=context,
                                system=SYSTEM, 
                                tools=TOOLS, # skills+safe_keys
                                builtin_tools=["Bash", "Editor", "WebSearch"], # "Canvas"
                                model="anthropic/claude-sonnet-4-6",
                                # model="openai/gpt-5.4",
                                show_usage=True
                            ):
        yield msg


super.local()
# super.deploy()