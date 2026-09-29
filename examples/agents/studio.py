# A Blender-style 3D studio in chat: the agent builds the scene, the user moves
# things by hand in the Studio app, real Blender renders it.
#
#   uv run cycls run examples/agents/studio.py      # localhost:8080
#
# Needs a Blender engine deployment (cycls-render, see docs/notes/studio.md) and,
# in .providers.env: ANTHROPIC_API_KEY, CYCLS_STUDIO_ENGINE=cycls-render and
# CYCLS_API_KEY (cycls.remote calls the engine with it).
import cycls

llm = (
    cycls.LLM()
    .model("anthropic/claude-sonnet-5")
    .system("You are a 3D artist working in the Studio with the user. Build what they describe, "
            "keep it tasteful and well lit, and explain briefly what you did.")
    .allowed_tools(["Studio", "Canvas"])
)


@cycls.agent(
    image=cycls.Image().copy(".providers.env", ".env"),
    web=cycls.Web().auth(cycls.Clerk()).title("Studio"),
    volumes={"/workspace": cycls.Volume("studio-agent")},
)
async def studio(context):
    async for ev in llm.run(context=context):
        yield ev
