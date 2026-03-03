# uv run examples/agent/super.py
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


@cycls.app(auth=True, analytics=True, copy=[".env"], force_rebuild=False)
async def super(context):
    print("context.messages.raw:", context.messages.raw)
    async for msg in cycls.Agent(context=context,
                                 system=SYSTEM, 
                                 tools=TOOLS, 
                                 builtin_tools=["Bash", "Editor", "WebSearch"],
                                 model="claude-sonnet-4-6",
                                 show_usage=True):
        yield msg


super.local()
# super.deploy()
