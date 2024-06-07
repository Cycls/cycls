# cycls-py

**sync**
```py
from cycls import Cycls, Text, Message

push = Cycls()

@push("hello")
def app(m: Message):
    return Text(m.content)
```

**async**
```py
from cycls import Cycls, Text, Message

push = Cycls()

@push("hello")
async def app(m: Message):
    return Text(m.content)
```

**debug**
```py
push = Cycls(debug=True)
```