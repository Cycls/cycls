# An agent that answers questions by querying the warehouse.
#
#   uv run cycls deploy examples/warehouse/query.py     # deploy the read side first
#   uv run cycls run examples/warehouse/analyst.py
#
# The agent image holds no data and no DuckDB. It calls the deployed `query`
# endpoint, which keeps the chat container small and the warehouse in one place.
import asyncio

import cycls

TOOLS = [
    {
        "name": "warehouse_sql",
        "description": (
            "Run read-only SQL over the events warehouse. One table: "
            "events(day DATE, country TEXT, product TEXT, amount DOUBLE). "
            "Write one query, read the result, then answer in plain language."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"sql": {"type": "string"}},
            "required": ["sql"],
        },
    }
]

run_sql = cycls.remote("query")


async def warehouse_sql(args):
    # cycls.remote(...) is a blocking call, so keep it off the event loop.
    result = await asyncio.to_thread(run_sql, args["sql"])
    if not result["rows"]:
        return "No rows."
    header = " | ".join(result["columns"])
    body = "\n".join(" | ".join(str(c) for c in row) for row in result["rows"][:50])
    return f"{header}\n{body}"


llm = (
    cycls.LLM()
    .model("anthropic/claude-sonnet-4-6")
    .system("You answer questions about sales using the warehouse_sql tool.")
    .tools(TOOLS)
    .on("warehouse_sql", warehouse_sql, label=lambda i: i["sql"][:60], details=True)
)


@cycls.agent(
    image=cycls.Image().copy(".providers.env", ".env"),
    web=cycls.Web().auth(cycls.Clerk()).title("Analyst"),
    volumes={"/workspace": cycls.Volume("analyst-chats")},
)
async def analyst(context):
    async for ev in llm.run(context=context):
        yield ev
