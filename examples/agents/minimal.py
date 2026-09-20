# The smallest agent: a chat product with a managed model loop.
#
#   uv run cycls run examples/agents/minimal.py      # localhost:8080
#   uv run cycls deploy examples/agents/minimal.py   # https://minimal.cycls.ai
#
# Needs ANTHROPIC_API_KEY in .providers.env, which ships into the container as
# .env. Keep CYCLS_API_KEY in .env on your machine, out of the image.
import cycls

image = cycls.Image().copy(".providers.env", ".env")

llm = (
    cycls.LLM()
    .model("anthropic/claude-sonnet-4-6")
    .system("You are a helpful assistant. Be concise.")
    .allowed_tools(["Bash", "Editor", "WebSearch", "Canvas"])
    .sandbox(network=False)          # bash has no egress; web search still works
    .price(input=3, output=15, cache_read=0.30, cache_write=6)
)


@cycls.agent(
    image=image,
    web=cycls.Web().auth(cycls.Clerk()).title("Minimal"),
    volumes={"/workspace": cycls.Volume("minimal-chats")},   # chats and files live here
)
async def minimal(context):
    async for ev in llm.run(context=context):
        yield ev
