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


# Show me a cat. Use the render_image tool with this URL: https://images.unsplash.com/photo-1514888286974-6c03e2ca1dba?w=800
async def render_image(args):
    return {"type": "text", "text": f"![{args.get('alt', '')}]({args['src']})"}

llm = (
    cycls.LLM()
    .model("anthropic/claude-sonnet-4-6")
    # .model("openai/gpt-5.4")
    .system(SYSTEM)
    .tools(TOOLS)  # skills+safe_keys
    .on("render_image", render_image)
    .allowed_tools(["Bash", "Editor", "WebSearch"])  # "Canvas"
    # .show_usage(True)
)


@cycls.agent(
    auth=cycls.Clerk(),
    analytics=True, # web=["Auth", "Analytics"]
    plan="cycls_pass",
    copy=[".env"],
    force_rebuild=False,
    title="The agent for getting things done"
)
async def super(context):
    # yield f"{context.user.plan}\n\n"
    # print(context.messages.raw)
    async for msg in llm.run(context=context):
        yield msg


# super.local()
super.deploy()