# uv run cycls run examples/agent/super.py
# uv run cycls deploy examples/agent/super.py
# cd client && npm run dev
# uv run pytest tests/agent_test.py -v

from datetime import datetime, timezone

import cycls

FREE_MONTHLY_LIMIT = 5
DOMAIN = "cycls.ai"
EXEMPT_USERS = {
    "user_2yY1NGlkgUtCgYiPLSHQUriCWrr",
    "user_2yXuICg28R0J2xXMDb6csQ0iEu9",
    "user_32PvPiUrZ649nniAJrLjzGSTRnS",
    "user_36FACLzxj35TJLMiYhGGj30k3bt",
    "user_3C4OrVnUh3PbayK89C73tqYPzOD",
}

image = cycls.Image().copy(".providers.env", ".env")#.rebuild()

web = (
    cycls.Web()
    .auth(cycls.Clerk(DOMAIN))
    .cms(DOMAIN)
    .analytics(True) # "cycls.ai"
    .title("The agent for getting things done")
)

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
    # .tools(TOOLS)  # skills+safe_keys
    # .on("render_image", render_image)
    .allowed_tools(["Bash", "Editor", "WebSearch"])  # "Canvas"
    .sandbox(network=True)
    # .show_usage(True)
)


@cycls.agent(image=image, web=web)
async def super(context):
    user = context.user
    # Local dev is always exempted so prototyping isn't blocked by gates.
    exempt = user.id in EXEMPT_USERS or not context.prod

    # b2b: free orgs blocked (no compute, no tracking)
    if user.plan == "o:free_org" and not exempt:
        yield {"type": "text", "text": "🔒 This workspace needs a paid plan."}
        yield {"type": "ui", "action": "open_plan_modal"}
        return

    # Track monthly usage; gate free users at FREE_MONTHLY_LIMIT.
    with context.workspace():
        usage = cycls.Dict("usage")
        month = datetime.now(timezone.utc).strftime("%Y-%m")
        entry = usage.get(month, {"count": 0})

        if user.plan == "u:free_user" and entry["count"] >= FREE_MONTHLY_LIMIT and not exempt:
            yield {"type": "text",
                   "text": f"🚨 Free tier limit reached ({FREE_MONTHLY_LIMIT}/mo). Upgrade for unlimited."}
            yield {"type": "ui", "action": "open_plan_modal"}
            return

        entry["count"] += 1
        usage[month] = entry

    async for msg in llm.run(context=context):
        yield msg


# uv run examples/agent/super.py
# if __name__ == "__main__":
#     super.local()
#     super.deploy()
#     pass
