# An agent on an open weight model. The only difference from an Anthropic agent
# is three lines: the vendor prefix, the base URL and the key.
#
#   uv run cycls run examples/agents/open_model.py
#   uv run cycls deploy examples/agents/open_model.py
#
# Put the provider key in .env on your machine. `import cycls` loads it, and
# `.api_key(...)` reads it here, so the value travels in the deployment:
#   DEEPSEEK_API_KEY=...      MOONSHOT_API_KEY=...      ZAI_API_KEY=...
#
# The Anthropic and OpenAI SDKs read ANTHROPIC_API_KEY and OPENAI_API_KEY from
# the container instead, which is why examples for those ship .providers.env and
# never call .api_key().
import os

import cycls

image = cycls.Image().copy(".providers.env", ".env")

# The vendor prefix selects the reasoning dialect, so use the one that matches
# the API you are calling, even when you host the model yourself.
llm = (
    cycls.LLM()
    .model("deepseek/deepseek-flash")
    .base_url("https://api.deepseek.com/v1")
    .api_key(os.environ.get("DEEPSEEK_API_KEY"))
    .system("You are a helpful assistant. Be concise.")
    .allowed_tools(["Bash", "Editor", "WebSearch", "Canvas"])
    .web_search("brave")             # portable search, works on any provider
    .thinking("medium")              # translated into the vendor's own dialect
    .context(128_000)                # when compaction starts; the default assumes 1M
    .max_tokens(8_192)
    .price(input=0.27, output=1.10)  # vendor rates, USD per million tokens
)

# Kimi K3, same shape:
#   .model("moonshotai/kimi-k3").base_url("https://api.moonshot.ai/v1")
#   .api_key(os.environ.get("MOONSHOT_API_KEY")).context(1_000_000)
#
# GLM, which is text only, so turn vision off:
#   .model("zai/glm-5.3").base_url("https://open.bigmodel.cn/api/paas/v4")
#   .api_key(os.environ.get("ZAI_API_KEY")).vision(False)
#
# Your own vLLM or SGLang server. `local` has no reasoning dialect, so send the
# parameter yourself:
#   .model("local/kimi-k3").base_url("http://localhost:8000/v1").api_key("unused")
#   .extra_body({"reasoning_effort": "high"})


@cycls.agent(
    image=image,
    web=cycls.Web().auth(cycls.Clerk()).title("Open agent"),
    volumes={"/workspace": cycls.Volume("open-agent")},
)
async def open_model(context):
    async for ev in llm.run(context=context):
        yield ev
