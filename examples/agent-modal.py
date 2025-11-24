import cycls

agent = cycls.Agent(pip=["openai"], modal_keys=["ak-", "as-"])

async def llm(x):
    import openai
    c, m = openai.AsyncOpenAI(api_key="sk-"), "gpt-4o"
    response = await c.chat.completions.create(model=m, messages=x, temperature=1.0, stream=True)
    async def event_stream():
        async for chunk in response:
            content = chunk.choices[0].delta.content
            if content:
                yield content
    return event_stream()

@agent("cake", auth=False)
async def func(context):
    return await llm(context.messages)

agent.modal()