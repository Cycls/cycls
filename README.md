# cycls-dev

```py
from fastapi import FastAPI
from pydantic import BaseModel

from functools import wraps
import inspect

class Message(BaseModel):
    content: str
    handle: str

app = FastAPI()

class Cycls:
    def __init__(self, path: str):
        self.path = path

    def __call__(self, func):
        if inspect.iscoroutinefunction(func):
            @wraps(func)
            async def async_wrapper(*args, **kwargs):
                return await func(*args, **kwargs)
            app.post(self.path)(async_wrapper)
            return async_wrapper
        else:
            @wraps(func)
            def sync_wrapper(*args, **kwargs):
                return func(*args, **kwargs)
            app.post(self.path)(sync_wrapper)
            return sync_wrapper

# @Cycls("/main")
# async def push(m: Message):
#     print(f"Item name: {m.content} (async)")
#     return m.dict()

@Cycls("/main")
def push(m: Message):
    print(f"Item name: {m.content} (sync)")
    return m.dict()
```

---

```py
from cycls import Cycls, Text, Message

@Cycls("hi")
def app(m: Message):
    return Text(m.content)
```

```py
from cycls import Cycls, Text, Message

@Cycls("hi")
async def app(m: Message):
    return Text(m.content)
```
