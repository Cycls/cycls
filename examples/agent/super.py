# uv run cycls run examples/agent/super.py
# uv run cycls deploy examples/agent/super.py
# cd client && npm run dev
# uv run pytest tests/agent/ -v

from datetime import datetime, timezone

import cycls

FREE_MONTHLY_LIMIT = 5
EXEMPT_USERS = {
    "user_2yY1NGlkgUtCgYiPLSHQUriCWrr",
    "user_2yXuICg28R0J2xXMDb6csQ0iEu9",
    "user_32PvPiUrZ649nniAJrLjzGSTRnS",
    "user_36FACLzxj35TJLMiYhGGj30k3bt",
    "user_3C4OrVnUh3PbayK89C73tqYPzOD",
}

# .pip("pandas")/.apt("ffmpeg")/.run("...") add deps + build steps; .volume("/data")
# moves the workspace mount; .rebuild() forces a no-cache build.
image = cycls.Image().copy(".providers.env", ".env")#.rebuild()

web = (
    cycls.Web()
    .auth(cycls.Clerk())
    .cms(brand="https://cms.cycls.ai/agents/super", explore="https://cms.cycls.ai/agents")  # any CMS returning the contract JSON; token=... for private ones
    # Static branding — the same knobs without a CMS (static wins, piece by piece):
    # .brand(name="Super", description="The agent for getting things done",
    #        logo="assets/logo.svg", og="assets/og.png", favicon="assets/favicon.svg")
    # .brand(locale="ar", name="سوبر", description="وكيلك لإنجاز المهام")
    # .seo(title="Super — AI agent", description="Automate research, files and documents.")
    # .colors(primary="#7c3aed", secondary="#f3e8ff", primary_dark="#a78bfa")  # theme accents (any CSS color)
    # .head('<meta name="google-site-verification" content="...">')
    # .explore({"name": "Coder", "url": "https://coder.cycls.ai", "logo": "assets/coder.svg"})
    # /robots.txt, /sitemap.xml, /llms.txt, /og.png are served automatically —
    # derived from .seo()/.brand(), with JSON-LD in <head> so the sign-in-gated
    # page stays crawlable.
    .analytics(True) # "cycls.ai"
    .affiliate("059168")  # Rewardful referral tracking
    .title("The agent for getting things done")
    # .theme("default")   # "default" or "dev"
    # .suggestions(True)  # show starter prompts on the empty chat
    # .copy_public("assets/logo.png")  # static files served at /public/<name>
    # .workspaces()    # personal + team workspaces (docs/workspaces.md)
    # .max_upload(512) # per-file upload cap in MB
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
    # .model("zai/glm-5.2").base_url("https://api.z.ai/api/paas/v4/")  # any OpenAI-compatible API
    # .model("google/gemini-3.1-pro-preview").base_url("https://generativelanguage.googleapis.com/v1beta/openai/")
    # .context(200_000)   # window → compaction timing (default 1M; set for smaller models)
    .max_tokens(64_000)   # output cap per request (default 8k)
    .price(input=3, output=15, cache_read=0.30, cache_write=6)  # USD/1M, for cost tracking
    .system(SYSTEM)
    # .tools(TOOLS)  # custom tool JSON schemas
    # .on("render_image", render_image, label=lambda inp: inp.get("alt", ""))
    #   register a handler; label renders the UI step line, e.g. render_image(a cat)
    .allowed_tools(["Bash", "Editor", "WebSearch", "DataBase", "Canvas"])
    # .thinking("low")  # unified reasoning across providers: "low" | "medium" | "high"
    # .web_search("native")  # Anthropic server-side search; default "brave" runs on any model (BRAVE_API_KEY)
    # .skills("examples/agent/skills")  # ship skill folders (<name>/SKILL.md) with the agent
    # .instructions("AGENT.md")  # workspace instructions file in the system prompt — this is the default
    # .mcp(cycls.MCP("https://figma-mcp.example/mcp").name("figma").token(os.environ["FIGMA_TOKEN"]))  # remote MCP, anthropic/* only (needs `import os`)
    # .sandbox(network=False)  # opt out of network access for the LLM bash
    # .bash_timeout(600)  # bash sandbox timeout in seconds
    # .api_key(os.environ["ANTHROPIC_API_KEY"])  # override the provider key (default: from env)
    # .loop(my_loop)  # replace the built-in agent loop entirely (see docs/tutorial.md)
)


@cycls.agent(image=image, web=web, name="super")
async def super(context):
    user = context.user
    # Local dev is always exempted so prototyping isn't blocked by gates.
    exempt = user.id in EXEMPT_USERS or not context.prod

    # b2b: free orgs blocked (no compute, no tracking)
    if user.plan == "o:free_org" and not exempt:
        cycls.log("cap_hit", user=user, chat_id=context.chat_id, kind="org_free")
        yield {"type": "text", "text": "🔒 This workspace needs a paid plan."}
        yield {"type": "ui", "action": "open_plan_modal"}
        return

    # Track monthly usage; gate free users at FREE_MONTHLY_LIMIT.
    db = cycls.DB(context.workspace)
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    key = f"usage/{month}"
    entry = await db.get(key, {"count": 0})

    if user.plan == "u:free_user" and entry["count"] >= FREE_MONTHLY_LIMIT and not exempt:
        cycls.log("cap_hit", user=user, chat_id=context.chat_id,
                  kind="user_free_monthly", count=entry["count"], limit=FREE_MONTHLY_LIMIT)
        yield {"type": "text",
               "text": f"🚨 Free tier limit reached ({FREE_MONTHLY_LIMIT}/mo). Upgrade for unlimited."}
        yield {"type": "ui", "action": "open_plan_modal"}
        return

    entry["count"] += 1
    await db.put(key, entry)

    async for ev in llm.run(context=context):
        yield cycls.to_ui(ev)


# uv run examples/agent/super.py
# if __name__ == "__main__":
#     super.local()
#     super.deploy()
#     pass
