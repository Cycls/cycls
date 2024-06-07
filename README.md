### cycls-py

```sh
pip install cycls
```

### sync 
```py
from cycls import Cycls, Message, Text

push = Cycls()

@push("cake")
def app(m: Message):
    return Text(m.content)
```
`https://cycls.com/@cake`

### async
```py
from cycls import Cycls, Message, Text

push = Cycls()

@push("her")
async def app(m: Message):
    return Text(m.content)
```
`https://cycls.com/@her`

### debug
```py
push = Cycls(debug=True)
```

## groq example
```py
from cycls import Cycls, Message, Text
from groq import AsyncGroq

push = Cycls()

groq = AsyncGroq(api_key="YOUR_KEY")

async def llm(content):
    stream = await groq.chat.completions.create(
        messages=[
            {"role": "system", "content": "you are a helpful assistant."},
            {"role": "user", "content": content}
        ],
        model="llama3-70b-8192",
        temperature=0.5, max_tokens=1024, top_p=1, stop=None, 
        stream=True,
    )

    async def event_stream():
        async for chunk in stream:
            yield f"{chunk.choices[0].delta.content}"

    return event_stream()

@push("groq-app")
async def app(x:Message):
    stream = await llm(x.content)
    return Text(stream)
```
`https://cycls.com/@groq-app`


✦/✧
