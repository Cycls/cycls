</br></br><p align="center"><img src="https://cycls.com/static/assets/favicon.svg" alt="Cycls"></p></br>

<div align="center">
    <a href="https://pypi.org/project/cycls/" target="_blank" rel="noopener noreferrer">
        <img loading="lazy" src="https://img.shields.io/pypi/v/cycls.svg" alt="PyPI" class="img_ev3q" style="display: inline;">
    </a>
    <a href="https://discord.gg/BMnaMatDC7" target="_blank" rel="noopener noreferrer">
        <img loading="lazy" src="https://img.shields.io/discord/1175782747164389466" alt="Discord" class="img_ev3q" style="display: inline;">
    </a>
</div>

# cycls.py

```sh
pip install cycls
```

## sync app
```py
from cycls import Cycls, Message, Text

push = Cycls()

@push("cake")
def app(m: Message):
    return Text(m.content)
```
`https://cycls.com/@cake`

## async app
```py
from cycls import Cycls, Message, Text

push = Cycls()

@push("her")
async def app(m: Message):
    return Text(m.content)
```
`https://cycls.com/@her`

## debug
```py
push = Cycls(debug=True)
```

## groq app
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

## history
```py
@push("cake")
def app(m:Message):
   print(m.history)
   return Text(m.content)
```
`https://cycls.com/@cake`

## groq app with history
```py
from cycls import Cycls, Message, Text
from groq import AsyncGroq

push = Cycls()

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

@push("groq-app")
async def app(m:Message):
    x  = [{"role": "system", "content": "you are a helpful assistant."}]
    x +=  m.history
    x += [{"role": "user", "content": m.content}]
    stream = await llm(x)
    return Text(stream)
```
`https://cycls.com/@groq-app`

# Known issues
- Dev mode doesn't work on Windows machines
