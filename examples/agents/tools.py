# A custom tool: your JSON schema, your async handler. The return value is both
# the event the user sees and the tool_result the model reads.
#
#   uv run cycls run examples/agents/tools.py
import cycls

TOOLS = [
    {
        "name": "sentiment",
        "description": (
            "Score the sentiment of a piece of text from -1 to 1. "
            "Use when the user asks how positive or negative something reads."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
    },
    {
        "name": "render_chart",
        "description": "Draw a bar chart and show it in the conversation.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "labels": {"type": "array", "items": {"type": "string"}},
                "values": {"type": "array", "items": {"type": "number"}},
                "title": {"type": "string"},
            },
            "required": ["labels", "values"],
        },
    },
]

POSITIVE = {"good", "great", "love", "excellent", "happy", "fast"}
NEGATIVE = {"bad", "terrible", "hate", "slow", "broken", "angry"}


async def sentiment(args, ctx):
    # A second parameter is optional. When declared, it carries the caller:
    # ctx.user, ctx.workspace, ctx.chat_id, ctx.approvals, ctx.auto.
    words = args["text"].lower().split()
    hits = sum(w.strip(".,!?") in POSITIVE for w in words)
    misses = sum(w.strip(".,!?") in NEGATIVE for w in words)
    if not (hits or misses):
        return "Score 0.0 (no sentiment words found)."
    score = (hits - misses) / (hits + misses)
    who = ctx.user.id if ctx.user else "anonymous"
    cycls.log("sentiment", user=ctx.user, chat_id=ctx.chat_id, score=score)
    return f"Score {score:+.2f} for {who}: {hits} positive, {misses} negative."


async def render_chart(args):
    # Returning a component dict renders it instead of text.
    rows = "\n".join(
        f"{label} {'#' * max(1, round(value / max(args['values']) * 24))} {value:g}"
        for label, value in zip(args["labels"], args["values"])
    )
    return {"type": "code", "code": rows, "language": "text"}


llm = (
    cycls.LLM()
    .model("anthropic/claude-sonnet-4-6")
    .system("You are a data assistant. Use the tools rather than estimating.")
    .tools(TOOLS)
    .on("sentiment", sentiment, label=lambda i: i["text"][:40])
    .on("render_chart", render_chart, label=lambda i: i.get("title", "chart"))
)


@cycls.agent(
    image=cycls.Image().copy(".providers.env", ".env"),
    web=cycls.Web().auth(cycls.Clerk()).title("Tools"),
    volumes={"/workspace": cycls.Volume("tools-agent")},
)
async def tools(context):
    async for ev in llm.run(context=context):
        yield ev
