from groq import AsyncGroq

groq = AsyncGroq(api_key="YOUR_KEY")

async def llm(messages):
    stream = await groq.chat.completions.create(
        messages=messages,
        model="llama3-70b-8192",
        temperature=0.5, max_tokens=1024, top_p=1, stop=None, 
        stream=True,
    )

    async def event_stream():
        async for chunk in stream:
            yield f"{chunk.choices[0].delta.content}"

    return event_stream()

from cycls import Cycls, Message, Text

push = Cycls(debug=True)

@push("groq-app")
async def app(m:Message):
    x  = [{"role": "system", "content": "you are a helpful assistant."}]
    x +=  m.history
    x += [{"role": "user", "content": m.content}]
    stream = await llm(x)
    return Text(stream)

# @push("cake")
# def app(m:Message):
#   print(m.history)
#   return Text("hello world")