import cycls

@cycls.agent(pip=["openai"], modal_keys=["YOUR_MODAL_AK", "YOUR_MODAL_AS"])
async def chat(context):
    """Run an agent on Modal."""
    import openai

    client = openai.AsyncOpenAI()
    response = await client.chat.completions.create(
        model="gpt-4o",
        messages=context.messages,
        stream=True
    )

    async for chunk in response:
        if chunk.choices[0].delta.content:
            yield chunk.choices[0].delta.content

chat.modal()
