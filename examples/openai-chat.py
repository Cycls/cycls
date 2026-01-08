import cycls
from cycls import UI

agent = cycls.Agent(pip=["openai"], theme="dev")

@agent('openai-chat')
async def chat(context):
    from openai import AsyncOpenAI
    client = AsyncOpenAI()
    
    print(context.messages.raw)

    stream = await client.responses.create(
        model="o3-mini",
        input=context.messages,
        stream=True,
        reasoning={"effort": "medium", "summary": "auto"},
    )

    async for event in stream:
        if event.type == "response.reasoning_summary_text.delta":
            yield UI.thinking(event.delta)
        elif event.type == "response.output_text.delta":
            yield event.delta

agent.deploy(prod=False)
