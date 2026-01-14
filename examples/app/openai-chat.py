import cycls

@cycls.app(pip=["openai"], theme="dev")
async def openai_chat(context):
    from openai import AsyncOpenAI
    client = AsyncOpenAI()
    
    stream = await client.responses.create(
        model="o3-mini",
        input=context.messages,
        stream=True,
        reasoning={"effort": "medium", "summary": "auto"},
    )

    async for event in stream:
        if event.type == "response.reasoning_summary_text.delta":
            yield {"type": "thinking", "thinking": event.delta}
        elif event.type == "response.output_text.delta":
            yield event.delta

openai_chat.local()
