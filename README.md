### cycls-py

```sh
pip install cycls
```

### sync 
```py
from cycls import Cycls, Text, Message

push = Cycls()

@push("cake")
def app(m: Message):
    return Text(m.content)
```
`https://cycls.com/@cake`

### async
```py
from cycls import Cycls, Text, Message

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

✦/✧
