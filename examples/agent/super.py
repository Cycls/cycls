# uv run examples/agent/super.py
# cd client && npm run dev
# ✻ Prestidigitating… (2m 21s · ↓ 4.5k tokens)
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


@cycls.app(
    auth=True,      # web/config
    analytics=True, # web=["Auth", "Analytics"]
    copy=[".env"], 
    force_rebuild=False,
    theme="wafi",
    title="The agent for getting things done"
) 
async def super(context):
    # yield f"{context.user}\n\n"
    # print(context.messages.raw)
    async for msg in cycls.Agent(
                                context=context,
                                system=SYSTEM, 
                                tools=TOOLS, # skills+safe_keys
                                builtin_tools=["Bash", "Editor", "WebSearch"], # "Canvas"
                                model="claude-sonnet-4-6",
                                show_usage=False
                            ):
        yield msg


super.local()
# super.deploy()