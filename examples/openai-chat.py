import cycls
# from cycls import UI

agent = cycls.Agent(pip=["openai"], theme="dev")

def text_content(m):
    return "".join(p.get("content", "") for p in m.get("parts", []) if p.get("name") == "text")

@agent('openai-chat')
async def chat(context):
    from openai import AsyncOpenAI
    client = AsyncOpenAI()  # uses OPENAI_API_KEY env var
    print(context.messages)
    msgs = [{"role": m["role"], "content": m.get("content") or text_content(m)} for m in context.messages]
    print(msgs)
    stream = await client.chat.completions.create(
        model="gpt-4o-mini",
        messages=msgs,
        stream=True
    )
    async for chunk in stream:
        if content := chunk.choices[0].delta.content:
            # yield UI.thinking("I'm a thot")
            yield {"name": "thinking", "content": "I'm a thot"}
            yield content


agent.deploy(prod=False)
