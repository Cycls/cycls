# Standalone test deployment of the new-SDK build (this branch), under a fresh
# name so it never touches the production `super`.
#   uv run cycls deploy examples/agent/super_new.py
import cycls

# Ships ANTHROPIC/OPENAI keys into the image as .env (same as super.py).
image = cycls.Image().copy(".providers.env", ".env")

# Standalone test: auth only — no CMS registration, no analytics.
# workspaces(): personal + team workspaces (docs/workspaces.md).
web = (
    cycls.Web()
    .auth(cycls.Clerk())
    .title("Super (new SDK)")
    .workspaces()
)

SYSTEM = "You are Cycls.".strip()

llm = (
    cycls.LLM()
    .model("anthropic/claude-sonnet-4-6")
    .system(SYSTEM)
    .allowed_tools(["Bash", "Editor", "WebSearch", "DataBase", "Canvas"])
)


@cycls.agent(image=image, web=web, name="super-new")
async def super_new(context):
    async for ev in llm.run(context=context):
        yield cycls.to_ui(ev)
